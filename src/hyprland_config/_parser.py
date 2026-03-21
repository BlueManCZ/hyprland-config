"""Line classification and document construction."""

import re
from pathlib import Path

from hyprland_config._expr import expand_value
from hyprland_config._model import (
    Assignment,
    BlankLine,
    Comment,
    Conditional,
    Document,
    ErrorLine,
    Keyword,
    Line,
    SectionClose,
    SectionOpen,
    Source,
    Variable,
)
from hyprland_config._source import SourceCycleError, resolve_source_paths


class ParseError(Exception):
    """Raised when a config line cannot be parsed."""

    def __init__(self, message: str, source: str = "", lineno: int = 0) -> None:
        self.source = source
        self.lineno = lineno
        super().__init__(message)


_STATIC_KEYWORD_NAMES = frozenset(
    (
        "unbind",
        "monitor",
        "animation",
        "bezier",
        "env",
        "exec",
        "exec-once",
        "exec-shutdown",
        "workspace",
        "windowrule",
        "windowrulev2",
        "layerrule",
        "plugin",
        "submap",
    )
)

# Hyprland generates bind variants combinatorially from flag chars (e, l, r, n, m, t, i, s, d, p).
# A regex covers all current and future combinations without needing manual enumeration.
_BIND_RE = re.compile(r"^bind[elnrmtisdp]*$")


def is_keyword(name: str) -> bool:
    """Check whether a key name is a Hyprland keyword.

    Covers all bind flag combinations (bind, binde, bindm, bindrl, etc.)
    as well as static keywords (monitor, env, exec, etc.).
    """
    return name in _STATIC_KEYWORD_NAMES or _BIND_RE.match(name) is not None


# Match one-line block: "name { key = value }"
_ONELINE_BLOCK_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)(?:\[([^\]]*)\])?\s*\{(.+)\}\s*$")

# Match section open: "name {" or "name[key] {"
_SECTION_OPEN_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)(?:\[([^\]]*)\])?\s*\{\s*$")

# Match variable definition: $name = value
_VARIABLE_RE = re.compile(r"^\$([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.*?)\s*$")

# Match source directive
_SOURCE_RE = re.compile(r"^source\s*=\s*(.*?)\s*$")

# Match key = value (covers both assignments and keywords; distinguished by is_keyword())
_KEY_VALUE_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_:.\-]*)\s*=\s*(.*?)\s*$")

# Match hyprlang directives: # hyprlang if/elif/else/endif/noerror
_DIRECTIVE_RE = re.compile(r"^#\s*hyprlang\s+(if|elif|else|endif|noerror)(?:\s+(.+?))?\s*$")


def _strip_inline_comment(value: str) -> tuple[str, str]:
    """Strip trailing inline comment from a value string.

    Handles ## as an escaped #. Returns (value, comment).
    The comment includes the # prefix if present.
    """
    in_quote = False
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == '"':
            in_quote = not in_quote
        elif ch == "#" and not in_quote:
            if i + 1 < len(value) and value[i + 1] == "#":
                i += 2
                continue
            return value[:i].rstrip(), value[i:]
        i += 1
    return value, ""


def _classify_kv(
    raw: str,
    lineno: int,
    source_name: str,
    key: str,
    value_raw: str,
    full_key: str,
) -> Assignment | Keyword:
    """Build an Assignment or Keyword node from parsed key/value parts."""
    value, inline_comment = _strip_inline_comment(value_raw)
    cls = Keyword if is_keyword(key) else Assignment
    return cls(
        raw=raw,
        lineno=lineno,
        source_name=source_name,
        key=key,
        value=value,
        full_key=full_key,
        inline_comment=inline_comment,
    )


def _parse_line(
    raw: str,
    lineno: int,
    section_stack: list[str],
    source_name: str,
) -> Line:
    """Parse a single raw line into the appropriate Line node type.

    Mutates section_stack to track section nesting depth.
    """
    stripped = raw.strip()

    # Blank line
    if not stripped:
        return BlankLine(raw=raw, lineno=lineno, source_name=source_name)

    # Comment or conditional directive
    if stripped.startswith("#"):
        m = _DIRECTIVE_RE.match(stripped)
        if m:
            return Conditional(
                raw=raw,
                lineno=lineno,
                source_name=source_name,
                kind=m.group(1),
                expression=m.group(2) or "",
            )
        return Comment(raw=raw, lineno=lineno, source_name=source_name, text=stripped[1:].strip())

    # Section close
    if stripped == "}":
        if section_stack:
            section_stack.pop()
        return SectionClose(raw=raw, lineno=lineno, source_name=source_name)

    # One-line block: "name { key = value }"
    m = _ONELINE_BLOCK_RE.match(stripped)
    if m:
        # Treat as a single Assignment/Keyword with the section prefix
        block_name = m.group(1)
        block_key = m.group(2) or ""
        inner = m.group(3).strip()
        prefix = ":".join(section_stack + [block_name])
        if block_key:
            prefix = f"{prefix}[{block_key}]"

        # Parse inner content as assignment(s)
        # For simplicity, we preserve the whole line as-is and classify as Assignment
        inner_stripped = inner.rstrip(";").strip()
        inner_m = _KEY_VALUE_RE.match(inner_stripped)
        if inner_m:
            return _classify_kv(
                raw,
                lineno,
                source_name,
                key=inner_m.group(1),
                value_raw=inner_m.group(2),
                full_key=f"{prefix}:{inner_m.group(1)}",
            )
        # Fall through to treat as a generic keyword line
        return Keyword(
            raw=raw,
            lineno=lineno,
            source_name=source_name,
            key=block_name,
            value=inner,
            full_key=prefix,
        )

    # Section open: "name {" or "name[key] {"
    m = _SECTION_OPEN_RE.match(stripped)
    if m:
        name = m.group(1)
        sec_key = m.group(2) or ""
        section_stack.append(name)
        return SectionOpen(
            raw=raw, lineno=lineno, source_name=source_name, name=name, section_key=sec_key
        )

    # Variable definition: $name = value
    m = _VARIABLE_RE.match(stripped)
    if m:
        return Variable(
            raw=raw, lineno=lineno, source_name=source_name, name=m.group(1), value=m.group(2)
        )

    # Source directive
    m = _SOURCE_RE.match(stripped)
    if m:
        return Source(raw=raw, lineno=lineno, source_name=source_name, path_str=m.group(1))

    # Assignment or keyword: key = value
    m = _KEY_VALUE_RE.match(stripped)
    if m:
        key = m.group(1)
        if section_stack and ":" not in key:
            full_key = ":".join(section_stack + [key])
        else:
            full_key = key
        return _classify_kv(raw, lineno, source_name, key, m.group(2), full_key)

    raise ParseError(
        f"{source_name}:{lineno}: could not parse: {stripped!r}",
        source=source_name,
        lineno=lineno,
    )


def parse_string(
    text: str,
    *,
    name: str = "<string>",
    lenient: bool = False,
) -> Document:
    """Parse a config string into a Document.

    When *lenient* is True, unparseable lines are stored as ``ErrorLine``
    nodes instead of raising ``ParseError``.  This lets tools report
    multiple issues at once.  The resulting document's ``.errors``
    property lists all collected ``ErrorLine`` nodes.
    """
    lines: list[Line] = []
    variables: dict[str, str] = {}
    section_stack: list[str] = []

    raw_lines = text.splitlines(keepends=True)

    for lineno, raw in enumerate(raw_lines, start=1):
        try:
            node = _parse_line(raw, lineno, section_stack, name)
        except ParseError as exc:
            if not lenient:
                raise
            node = ErrorLine(
                raw=raw,
                lineno=lineno,
                source_name=name,
                message=str(exc),
            )
        lines.append(node)

        if isinstance(node, Variable):
            variables[node.name] = node.value

    return Document(path=None, lines=lines, variables=variables)


def parse_file(
    path: Path,
    *,
    _seen: set[Path] | None = None,
    follow_sources: bool = False,
    lenient: bool = False,
) -> Document:
    """Parse a config file into a Document.

    If follow_sources is True, source directives are resolved and each
    Source node gets a .documents list of parsed sub-Documents. Variables
    from sourced files are merged into the root document.

    When *lenient* is True, unparseable lines become ``ErrorLine`` nodes
    instead of raising ``ParseError``.
    """
    path = path.resolve()

    if _seen is None:
        _seen = set()
    if path in _seen:
        raise SourceCycleError(path)
    _seen.add(path)

    text = path.read_text(encoding="utf-8")
    doc = parse_string(text, name=str(path), lenient=lenient)
    doc.path = path

    if follow_sources:
        doc.sources_followed = True
        _follow_sources(doc, _seen, lenient=lenient)

    return doc


def _follow_sources(doc: Document, seen: set[Path], *, lenient: bool = False) -> None:
    """Resolve Source nodes and attach parsed sub-Documents."""
    for node in doc.lines:
        if not isinstance(node, Source):
            continue

        expanded_path = expand_value(node.path_str, doc.variables)
        relative_to = doc.path.parent if doc.path else None
        resolved = resolve_source_paths(expanded_path, relative_to=relative_to)
        node.resolved_paths = resolved

        for rpath in resolved:
            if rpath.resolve() in seen:
                continue
            try:
                sub_doc = parse_file(rpath, _seen=seen, follow_sources=True, lenient=lenient)
                node.documents.append(sub_doc)
                doc.variables.update(sub_doc.variables)
            except (FileNotFoundError, SourceCycleError):
                continue
