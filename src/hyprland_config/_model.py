"""Document model — flat line list with node types for lossless round-trip editing."""

from collections.abc import Callable, Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import cast

from hyprland_config._expr import expand_value
from hyprland_config._writer import atomic_write

_INDENT = "    "


def _has_glob_chars(pattern: str) -> bool:
    """Check if a string contains glob metacharacters."""
    return any(c in pattern for c in ("*", "?", "["))


def _format_kv_line(indent: str, key: str, value: str, inline_comment: str = "") -> str:
    """Build a formatted key = value line string."""
    comment_suffix = f" {inline_comment}" if inline_comment else ""
    return f"{indent}{key} = {value}{comment_suffix}\n"


@dataclass
class Line:
    """Base class for all line nodes."""

    raw: str
    lineno: int = 0
    source_name: str = ""

    @property
    def indent(self) -> str:
        """Leading whitespace of the raw line."""
        return self.raw[: len(self.raw) - len(self.raw.lstrip())]


@dataclass
class BlankLine(Line):
    """Empty or whitespace-only line."""


@dataclass
class Comment(Line):
    """Comment line (# text), including #! and ## escapes."""

    text: str = ""


@dataclass
class Variable(Line):
    """Variable definition: $name = value."""

    name: str = ""
    value: str = ""


@dataclass
class KeyValueLine(Line):
    """Base for lines with key = value semantics (assignments and keywords)."""

    key: str = ""
    value: str = ""
    full_key: str = ""
    inline_comment: str = ""


@dataclass
class Assignment(KeyValueLine):
    """Key = value assignment."""


@dataclass
class Source(Line):
    """source = path directive."""

    path_str: str = ""
    resolved_paths: list[Path] = field(default_factory=list)
    documents: list["Document"] = field(default_factory=list)


@dataclass
class SectionOpen(Line):
    """category { or category[key] {."""

    name: str = ""
    section_key: str = ""


@dataclass
class SectionClose(Line):
    """Closing brace }."""


@dataclass
class Keyword(KeyValueLine):
    """Special keyword line (bind, monitor, env, exec, etc.)."""


@dataclass
class Conditional(Line):
    """Hyprlang directive: # hyprlang <kind> [expression].

    kind is one of "if", "elif", "else", "endif", "noerror".
    expression holds the condition text (empty for else/endif),
    or "true"/"false" for noerror directives.
    """

    kind: str = ""
    expression: str = ""


@dataclass
class ErrorLine(Line):
    """Unparseable line preserved in lenient parsing mode.

    Stores the error message so tools can report all issues at once.
    The raw text is preserved for lossless round-trip.
    """

    message: str = ""


def _match_key(
    ln: Line,
    key: str,
    matches: Callable[[str, str], bool] = str.__eq__,
) -> bool:
    """Match a KeyValueLine by key.

    Keywords (bind, monitor, animation, …) match on their bare ``key``
    OR ``full_key`` because Hyprland ignores section context for these.
    This means ``find("animation")`` matches ``animation`` inside an
    ``animations { }`` section, and ``find("animations:animation")``
    also works.  Assignments match on ``full_key`` only.

    *matches* compares two strings; defaults to equality, but ``fnmatch``
    is used for glob patterns.
    """
    if not isinstance(ln, KeyValueLine):
        return False
    if isinstance(ln, Keyword):
        return matches(ln.key, key) or matches(ln.full_key, key)
    return matches(ln.full_key, key)


def _key_predicate(key: str) -> Callable[[Line], bool]:
    """Build a predicate for matching KeyValueLine nodes by key or glob pattern."""
    if _has_glob_chars(key):
        return lambda ln: _match_key(ln, key, fnmatch)
    return lambda ln: _match_key(ln, key)


class Document:
    """A parsed Hyprland config file — flat list of Line nodes."""

    def __init__(
        self,
        path: Path | None = None,
        lines: list[Line] | None = None,
        variables: dict[str, str] | None = None,
        *,
        sources_followed: bool = False,
    ) -> None:
        self.path = path
        self.lines: list[Line] = lines if lines is not None else []
        self.variables: dict[str, str] = variables if variables is not None else {}
        self.dirty: bool = False
        self.sources_followed: bool = sources_followed

    @property
    def errors(self) -> list[ErrorLine]:
        """All parse errors collected during lenient parsing.

        Returns ErrorLine nodes from this document and all sourced
        sub-documents (depth-first).
        """
        return [
            line
            for doc in self._iter_all_documents()
            for line in doc.lines
            if isinstance(line, ErrorLine)
        ]

    def _mark_dirty(self) -> None:
        self.dirty = True

    def _resolve_recursive(self, recursive: bool | None) -> bool:
        return self.sources_followed if recursive is None else recursive

    def _iter_source_docs(self) -> Iterator["Document"]:
        """Yield all sub-Documents from Source nodes, depth-first."""
        for line in self.lines:
            if isinstance(line, Source):
                for sub in line.documents:
                    yield sub
                    yield from sub._iter_source_docs()

    def _iter_all_documents(self) -> Iterator["Document"]:
        """Yield self followed by all sub-Documents, depth-first."""
        yield self
        yield from self._iter_source_docs()

    def _target_documents(self, recursive: bool | None) -> Iterator["Document"]:
        """Yield documents to operate on based on recursive flag."""
        if self._resolve_recursive(recursive):
            yield from self._iter_all_documents()
        else:
            yield self

    def _iter_lines_recursive(
        self,
        exclude_sources: frozenset[Path] = frozenset(),
    ) -> Iterator[tuple["Document", Line]]:
        """Yield (document, line) pairs in Hyprland evaluation order.

        Source directives are expanded at the point they appear, so a sourced
        document's lines come at the position of the source directive in the
        parent. This matches Hyprland's "last value wins" semantics correctly.

        *exclude_sources*: resolved paths whose Source documents should be
        skipped during traversal. The Source line itself is still yielded,
        but its sub-documents are not expanded.
        """
        for line in self.lines:
            if isinstance(line, Source):
                yield self, line
                if exclude_sources and any(
                    rp.resolve() in exclude_sources for rp in line.resolved_paths
                ):
                    continue
                for sub in line.documents:
                    yield from sub._iter_lines_recursive(exclude_sources)
            else:
                yield self, line

    def _iter_lines(
        self,
        recursive: bool | None,
        exclude_sources: frozenset[Path] = frozenset(),
    ) -> Iterator[tuple["Document", Line]]:
        """Yield (document, line) pairs in correct evaluation order.

        When recursive, source directives are expanded at the point they
        appear — matching Hyprland's semantics. When not recursive, yields
        only this document's lines.
        """
        if self._resolve_recursive(recursive):
            yield from self._iter_lines_recursive(exclude_sources)
        else:
            for line in self.lines:
                yield self, line

    def _find_last(
        self,
        predicate: Callable[[Line], bool],
        recursive: bool | None = None,
        exclude_sources: frozenset[Path] = frozenset(),
    ) -> tuple["Document", Line] | None:
        """Find the last line matching predicate in evaluation order.

        Returns (owning_document, line) or None.
        """
        result: tuple["Document", Line] | None = None
        for doc, line in self._iter_lines(recursive, exclude_sources):
            if predicate(line):
                result = (doc, line)
        return result

    def _remove_matching_lines(self, predicate: Callable[[Line], bool]) -> None:
        """Remove lines matching predicate and mark dirty if any were removed."""
        before = len(self.lines)
        self.lines = [line for line in self.lines if not predicate(line)]
        if len(self.lines) != before:
            self._mark_dirty()

    def serialize(self) -> str:
        """Reconstruct the original file text from line nodes."""
        return "".join(line.raw for line in self.lines)

    # -- Query API --

    def get(
        self,
        key: str,
        default: str | None = None,
        *,
        recursive: bool | None = None,
        exclude_sources: frozenset[Path] = frozenset(),
    ) -> str | None:
        """Get the value of a config option by full_key.

        *exclude_sources*: resolved paths whose Source documents should be
        skipped during resolution. Use this to answer "what would this key
        resolve to without source X?".

        Returns the value as a string, or default if not found.
        """
        node = self.find(key, recursive=recursive, exclude_sources=exclude_sources)
        if node is None:
            return default
        return node.value

    def get_all(self, key: str, *, recursive: bool | None = None) -> list[str]:
        """Get all values for a key. Useful for repeated keywords like bind, env, monitor."""
        return [line.value for line in self.find_all(key, recursive=recursive)]

    def find(
        self,
        key: str,
        *,
        recursive: bool | None = None,
        exclude_sources: frozenset[Path] = frozenset(),
    ) -> Assignment | Keyword | None:
        """Find the last Assignment or Keyword matching a full_key or glob pattern.

        Supports glob patterns (``*``, ``?``, ``[…]``) for matching keys:
        - ``"input:touchpad:*"`` — all touchpad settings
        - ``"bind*"`` — all bind variants

        recursive defaults to True when sources were followed during parsing.
        Walks lines in Hyprland evaluation order — last match wins.
        """
        result = self._find_last(_key_predicate(key), recursive, exclude_sources)
        if result is None:
            return None
        return cast(Assignment | Keyword, result[1])

    def find_all(
        self,
        key: str,
        *,
        recursive: bool | None = None,
        exclude_sources: frozenset[Path] = frozenset(),
    ) -> list[Assignment | Keyword]:
        """Find all Assignment or Keyword lines matching a full_key or glob pattern.

        Supports glob patterns (``*``, ``?``, ``[…]``) for matching keys:
        - ``"input:touchpad:*"`` — all touchpad settings
        - ``"bind*"`` — all bind variants

        *exclude_sources*: resolved paths whose Source documents should be
        skipped during traversal.

        recursive defaults to True when sources were followed during parsing.
        Returns results in Hyprland evaluation order.
        """
        predicate = _key_predicate(key)
        return cast(
            list[Assignment | Keyword],
            [
                line
                for _doc, line in self._iter_lines(recursive, exclude_sources)
                if predicate(line)
            ],
        )

    def expand(self, text: str) -> str:
        """Fully expand a Hyprland config value (variables, expressions, escapes)."""
        return expand_value(text, self.variables)

    # -- Mutation API --

    def set_variable(self, name: str, value: str, *, recursive: bool | None = None) -> None:
        """Set a config variable ($name = value).

        Updates the last occurrence of the variable if it exists, or inserts
        a new variable definition at the top of the document (after any
        existing variables). Also updates the variables dict.
        """
        self.variables[name] = value

        # Find last Variable node with this name
        result = self._find_last(
            lambda ln: isinstance(ln, Variable) and ln.name == name,
            recursive,
        )

        if result is not None:
            target_doc, target_line = result
            target_var = cast(Variable, target_line)
            target_var.value = value
            target_var.raw = f"{target_var.indent}${name} = {value}\n"
            target_doc._mark_dirty()
        else:
            # Insert after last existing Variable line, or at the top
            insert_idx = 0
            for i, line in enumerate(self.lines):
                if isinstance(line, Variable):
                    insert_idx = i + 1
            node = Variable(raw=f"${name} = {value}\n", name=name, value=value)
            self.lines.insert(insert_idx, node)
            self._mark_dirty()

    def set(
        self, key: str, value: str | int | float | bool, *, recursive: bool | None = None
    ) -> None:
        """Set a config option by full_key. Updates last occurrence or inserts new.

        value is converted to string automatically (bool → "true"/"false").
        recursive defaults to True when sources were followed during parsing.
        Updates the last occurrence wherever it lives.
        If the key doesn't exist anywhere, inserts into this document.
        """
        if isinstance(value, bool):
            value = "true" if value else "false"
        else:
            value = str(value)

        result = self._find_last(lambda ln: _match_key(ln, key), recursive)

        if result is not None:
            target_doc, target_line = result
            kv_line = cast(KeyValueLine, target_line)
            kv_line.value = value
            kv_line.raw = _format_kv_line(
                kv_line.indent, kv_line.key, value, kv_line.inline_comment
            )
            target_doc._mark_dirty()
        else:
            self._insert_assignment(key, value)
            self._mark_dirty()

    def remove(self, key: str, *, recursive: bool | None = None) -> None:
        """Remove all Assignment or Keyword lines matching a full_key.

        recursive defaults to True when sources were followed during parsing.
        """
        match = _key_predicate(key)
        for doc in self._target_documents(recursive):
            doc._remove_matching_lines(match)

    def remove_where(
        self, keyword: str, predicate: Callable[[str], bool], *, recursive: bool | None = None
    ) -> None:
        """Remove Keyword lines where predicate(args) is True.

        Example: doc.remove_where("bind", lambda v: "killactive" in v)
        recursive defaults to True when sources were followed during parsing.
        """
        for doc in self._target_documents(recursive):
            doc._remove_matching_lines(
                lambda ln: isinstance(ln, Keyword) and ln.key == keyword and predicate(ln.value)
            )

    def append(self, keyword: str, args: str, *, recursive: bool | None = None) -> None:
        """Append a keyword line (bind, monitor, env, etc.).

        Inserts after the last occurrence of the same keyword in evaluation
        order. If none exists anywhere, appends to this document.
        """
        result = self._find_last(
            lambda ln: isinstance(ln, Keyword) and ln.key == keyword,
            recursive,
        )

        if result is not None:
            target_doc, target_line = result
            existing = cast(Keyword, target_line)
            idx = next(i for i, ln in enumerate(target_doc.lines) if ln is existing)
            node = Keyword(
                raw=_format_kv_line(existing.indent, keyword, args),
                key=keyword,
                value=args,
                full_key=existing.full_key,
            )
            target_doc.lines.insert(idx + 1, node)
            target_doc._mark_dirty()
        else:
            node = Keyword(
                raw=_format_kv_line("", keyword, args),
                key=keyword,
                value=args,
                full_key=keyword,
            )
            self.lines.append(node)
            self._mark_dirty()

    # -- Insert helpers --

    def _insert_assignment(self, key: str, value: str) -> None:
        """Insert a new assignment, respecting the document's style."""
        parts = key.split(":")
        if len(parts) == 1:
            self._append_flat_assignment(key, value, key)
            return

        section_path = parts[:-1]
        leaf_key = parts[-1]

        insert_idx = self._find_section_insert_point(section_path)
        if insert_idx is not None:
            indent = _INDENT * len(section_path)
            node = Assignment(
                raw=_format_kv_line(indent, leaf_key, value),
                key=leaf_key,
                value=value,
                full_key=key,
            )
            self.lines.insert(insert_idx, node)
            return

        if self._uses_sections():
            self._create_section_with_assignment(section_path, leaf_key, value, key)
        else:
            self._append_flat_assignment(key, value, key)

    def _append_flat_assignment(self, key: str, value: str, full_key: str) -> None:
        """Append a top-level (unindented) assignment line."""
        self.lines.append(
            Assignment(raw=_format_kv_line("", key, value), key=key, value=value, full_key=full_key)
        )

    def _find_section_insert_point(self, section_path: list[str]) -> int | None:
        """Find the index just before the closing brace of the matching section."""
        target_depth = len(section_path)
        matched_depth = 0
        stack: list[str] = []

        for i, line in enumerate(self.lines):
            if isinstance(line, SectionOpen):
                stack.append(line.name)
                if len(stack) <= target_depth and stack == section_path[: len(stack)]:
                    matched_depth = len(stack)
            elif isinstance(line, SectionClose) and stack:
                if matched_depth == target_depth and len(stack) == target_depth:
                    return i
                stack.pop()
                if len(stack) < matched_depth:
                    matched_depth = len(stack)

        return None

    def _uses_sections(self) -> bool:
        """Detect whether the document uses section blocks."""
        return any(isinstance(line, SectionOpen) for line in self.lines)

    def _create_section_with_assignment(
        self, section_path: list[str], leaf_key: str, value: str, full_key: str
    ) -> None:
        """Create nested section blocks with an assignment inside."""
        if self.lines and not isinstance(self.lines[-1], BlankLine):
            self.lines.append(BlankLine(raw="\n"))

        for depth, name in enumerate(section_path):
            indent = _INDENT * depth
            self.lines.append(SectionOpen(raw=f"{indent}{name} {{\n", name=name))

        inner_indent = _INDENT * len(section_path)
        self.lines.append(
            Assignment(
                raw=_format_kv_line(inner_indent, leaf_key, value),
                key=leaf_key,
                value=value,
                full_key=full_key,
            )
        )

        for depth in range(len(section_path) - 1, -1, -1):
            indent = _INDENT * depth
            self.lines.append(SectionClose(raw=f"{indent}}}\n"))

    # -- Section Iteration API --

    def sections(self, *, recursive: bool | None = None) -> list[str]:
        """List all unique section names in document order.

        Returns section names like ["general", "decoration", "blur", "input", …].
        Includes nested sections (e.g. ``blur`` inside ``decoration``).
        """
        seen: set[str] = set()
        result: list[str] = []
        for _doc, line in self._iter_lines(recursive):
            if isinstance(line, SectionOpen) and line.name not in seen:
                seen.add(line.name)
                result.append(line.name)
        return result

    def section(
        self,
        name: str,
        *,
        key: str | None = None,
        recursive: bool | None = None,
    ) -> list[Line]:
        """Get the contents of a named section.

        Returns the lines inside the section block (excluding the open/close
        braces). For keyed sections like ``device[epic-mouse-v1] {``, pass
        the key parameter.

        If the section appears multiple times, all occurrences are merged.
        """
        result: list[Line] = []
        collecting = False
        depth = 0
        for _doc, line in self._iter_lines(recursive):
            if collecting:
                if isinstance(line, SectionOpen):
                    depth += 1
                    result.append(line)
                elif isinstance(line, SectionClose):
                    if depth == 0:
                        collecting = False
                    else:
                        depth -= 1
                        result.append(line)
                else:
                    result.append(line)
            elif (
                isinstance(line, SectionOpen)
                and line.name == name
                and (key is None or line.section_key == key)
            ):
                collecting = True
                depth = 0
        return result

    # -- Conversion --

    def to_dict(self) -> dict[str, str | list[str]]:
        """Build a flat dict from this document with variable expansion.

        Keys that appear once map to a string. Keys that appear multiple times
        (e.g. bind, env, monitor) map to a list of strings.

        Recurses into sourced sub-documents when sources were followed.
        """
        result: dict[str, str | list[str]] = {}
        for _sub_doc, line in self._iter_lines(None):
            if isinstance(line, KeyValueLine):
                value = expand_value(line.value, self.variables)
                key = line.full_key
                existing = result.get(key)
                if existing is None:
                    result[key] = value
                elif isinstance(existing, list):
                    existing.append(value)
                else:
                    result[key] = [existing, value]
        return result

    # -- Copy --

    def copy(self) -> "Document":
        """Create a deep copy of this document and all sourced sub-documents.

        The copy is independent — mutations to the copy do not affect the
        original, and vice versa. Useful for comparing before/after states
        or building diffs.
        """
        return deepcopy(self)

    # -- Inspection --

    def dirty_files(self) -> list[Path]:
        """Return paths of all documents that have unsaved modifications."""
        return [
            doc.path for doc in self._iter_all_documents() if doc.dirty and doc.path is not None
        ]

    # -- Persistence --

    def save(self, path: Path | None = None, *, recursive: bool | None = None) -> None:
        """Write the document to disk using atomic write.

        recursive defaults to True when sources were followed during parsing.
        Only files that were actually modified (dirty) are written.
        """
        if self._resolve_recursive(recursive):
            for sub in self._iter_source_docs():
                if sub.dirty:
                    sub.save(recursive=False)

        if self.dirty or path is not None:
            target = path or self.path
            if target is None:
                raise ValueError("No path specified and document has no path")
            atomic_write(target, self.serialize())
            self.dirty = False
