"""Lua source-formatting primitives and value coercion.

Used by every emitter so they produce consistent output: scalar coercion
(Hyprlang value string → Lua-ready Python value), Lua string/key/table
formatting, and a handful of helpers for ``exec, hyprctl keyword …``
shell-out translation.
"""

import re
import shlex
from dataclasses import dataclass
from typing import Any

from hyprland_config._core._expr import substitute_variables_with_markers
from hyprland_config._core._types import Color, Gradient
from hyprland_config._core._values import (
    FLOAT_LITERAL_RE,
    INT_LITERAL_RE,
    option_type,
    parse_hyprlang_bool,
)

INDENT = "    "

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Control-char delimiters wrap a Hyprlang variable name (``$mainMod`` →
# ``\x01mainMod\x02``) so the reference survives the assignment / bind /
# rule pipelines as an opaque token. ``coerce_value`` and ``quote_string``
# spot the marker and emit a ``LuaExpr`` instead of a quoted string, which
# lets the assembled output reference a Lua local (``var_mainMod``) rather
# than inlining the value. SOH/STX never appear in legitimate Hyprlang.
VAR_MARKER_OPEN = "\x01"
VAR_MARKER_CLOSE = "\x02"
LUA_VAR_PREFIX = "var_"

_NON_IDENT_RE = re.compile(r"[^A-Za-z0-9_]")


@dataclass(frozen=True, slots=True)
class LuaExpr:
    """A pre-rendered Lua expression that bypasses string quoting.

    Returned by :func:`coerce_value` / :func:`quote_string` when their input
    carries variable markers — the assembled source already references the
    appropriate ``var_*`` locals, so wrapping it in quotes would turn the
    code back into the literal string we're trying to avoid.
    """

    source: str


def expand_value_lua(text: str, variables: dict[str, str], referenced: dict[str, str]) -> str:
    """Expand ``$var`` references in *text* into marker-wrapped tokens.

    Wrapper over :func:`substitute_variables_with_markers` that knows
    this module's marker bytes. Use this — not ``Document.expand`` — in
    the Lua emitter when you want variable references to survive as
    Lua locals rather than be inlined.
    """
    return substitute_variables_with_markers(
        text, variables, referenced, VAR_MARKER_OPEN, VAR_MARKER_CLOSE
    )


def lua_var_name(hyprlang_name: str) -> str:
    """Map a Hyprlang variable name to a safe Lua identifier.

    The ``var_`` prefix sidesteps reserved Lua keywords (``$end``,
    ``$function``) and leading-digit names (``$1mod``) without a per-name
    escape table. Non-alphanumeric chars (Hyprlang allows hyphens) collapse
    to underscore.
    """
    safe = _NON_IDENT_RE.sub("_", hyprlang_name)
    return f"{LUA_VAR_PREFIX}{safe}"


def has_var_marker(s: str) -> bool:
    return VAR_MARKER_OPEN in s


def _split_marker_string(s: str) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []
    i = 0
    while i < len(s):
        if s[i] == VAR_MARKER_OPEN:
            end = s.find(VAR_MARKER_CLOSE, i + 1)
            if end == -1:
                # Malformed — treat the rest as literal so we never
                # silently drop user content.
                parts.append(("lit", s[i:]))
                break
            parts.append(("var", s[i + 1 : end]))
            i = end + 1
        else:
            next_marker = s.find(VAR_MARKER_OPEN, i)
            if next_marker == -1:
                parts.append(("lit", s[i:]))
                break
            parts.append(("lit", s[i:next_marker]))
            i = next_marker
    return parts


def to_lua_expr(s: str) -> LuaExpr:
    """Convert a marker-bearing string into a Lua expression.

    A single ``$name`` reference (no surrounding text) renders as the bare
    identifier ``var_name``. Mixed content (``$mainMod + SHIFT``) renders
    as a Lua concatenation: ``var_mainMod .. " + SHIFT"``.
    """
    parts = _split_marker_string(s)
    if len(parts) == 1:
        kind, val = parts[0]
        if kind == "var":
            return LuaExpr(lua_var_name(val))
        return LuaExpr(_quote_literal(val))
    fragments = [lua_var_name(val) if kind == "var" else _quote_literal(val) for kind, val in parts]
    # Drop empty literal chunks ("") that arise at marker boundaries.
    fragments = [f for f in fragments if f != '""']
    return LuaExpr(" .. ".join(fragments))


# Hyprland's Hyprlang parser reads a boolean field by looking at the leading
# token only — ``enabled = yes, please :)`` is accepted as truthy because
# the value starts with ``yes``. The ``\b`` boundary anchor stops the regex
# from mis-coercing ``yesterday``, ``offer``, ``nope``, ``oneshot``, etc.,
# where a bool word appears as a prefix but the field is genuinely a string.
# ``0``/``1`` are deliberately excluded — plenty of non-bool options legitimately
# take small integers, and without schema awareness we can't tell which is which.
_LENIENT_BOOL_RE = re.compile(r"^(true|false|yes|no|on|off)\b", re.IGNORECASE)

# Lua reserved words can't be used as bare-key identifiers in table literals.
_LUA_KEYWORDS = frozenset(
    {
        "and",
        "break",
        "do",
        "else",
        "elseif",
        "end",
        "false",
        "for",
        "function",
        "goto",
        "if",
        "in",
        "local",
        "nil",
        "not",
        "or",
        "repeat",
        "return",
        "then",
        "true",
        "until",
        "while",
    }
)


# ---------------------------------------------------------------------------
# Key handling
# ---------------------------------------------------------------------------


# Path components that Hyprlang spells with a leading dot inside the leaf key
# (``general:col.inactive_border``) rather than as a deeper colon level. The
# emitter flattens these into nested Lua tables; the reader uses the same
# constant to rejoin them with a dot when reconstructing Hyprlang full_keys.
DOT_PREFIX_KEYS = frozenset({"col"})


def split_key(full_key: str) -> list[str]:
    """Split a full key like ``general:col.inactive_border`` into nesting parts.

    Both ``:`` (Hyprlang section separator) and ``.`` (sub-prefix convention,
    e.g. ``col.inactive_border``) become nesting boundaries in the Lua table.
    Empty parts from leading/trailing separators are dropped.
    """
    return [part for part in re.split(r"[:.]", full_key) if part]


def set_nested(tree: dict[str, Any], path: list[str], value: Any) -> None:
    """Set ``tree[p1][p2]...[pN] = value``, creating intermediate dicts.

    If an intermediate node was previously bound to a non-dict value (e.g.
    ``general:gaps_in`` set as an int then ``general:gaps_in:override`` tried
    to nest under it), the non-dict value is replaced so we still produce
    valid Lua rather than crashing on malformed input.
    """
    if not path:
        return
    *parents, leaf = path
    node = tree
    for part in parents:
        existing = node.get(part)
        if not isinstance(existing, dict):
            node[part] = {}
        node = node[part]
    node[leaf] = value


# ---------------------------------------------------------------------------
# Value coercion + formatting
# ---------------------------------------------------------------------------


def coerce_value(s: str) -> Any:
    """Best-effort coerce a Hyprlang value string to a Lua-ready Python value.

    Without schema awareness we key off the literal shape:

    - exact integer/float literals become numbers,
    - boolean words Hyprland's Hyprlang parser recognises
      (``true``/``yes``/``on`` and ``false``/``no``/``off``, case-insensitive)
      become booleans. The match is lenient on the trailing characters — a
      decorative ``enabled = yes, please :)`` line still coerces to ``true``
      because Hyprland's bool parser ignores everything after the leading
      token. The ``\\b`` boundary anchor avoids mis-coercing identifiers
      that merely start with a bool word (``yesterday``, ``oneshot``,
      ``offer``, …),
    - multi-colour gradients (``rgba(…) rgba(…) 45deg``) become a structured
      ``{colors = {…}, angle = N}`` dict, matching the form Hyprland's Lua API
      uses in the official example,
    - a single colour with a redundant ``0deg`` (``0xffed333b 0deg``) sheds the
      no-op angle and stays a bare-colour string, since Hyprland's Lua parser
      rejects the ``"<colour> 0deg"`` form (see :func:`_drop_zero_angle`),
    - everything else (single colours, paths, vec2, free text) stays a string.
    """
    stripped = s.strip()
    if has_var_marker(stripped):
        # Multi-colour gradients still need the structured ``{colors=…,
        # angle=…}`` shape — Hyprland's Lua API routes single-string
        # values to a different code path. Variable references survive
        # as ``LuaExpr`` entries inside the ``colors`` list.
        gradient = _try_gradient_with_markers(stripped)
        if gradient is not None:
            return gradient
        return to_lua_expr(stripped)
    if INT_LITERAL_RE.match(stripped):
        return int(stripped)
    if FLOAT_LITERAL_RE.match(stripped):
        return float(stripped)
    bool_match = _LENIENT_BOOL_RE.match(stripped)
    if bool_match is not None:
        return parse_hyprlang_bool(bool_match.group(1))
    gradient = _try_gradient(stripped)
    if gradient is not None:
        return gradient
    bare_color = _drop_zero_angle(stripped)
    if bare_color is not None:
        return bare_color
    return s


def coerce_option_value(full_key: str, value: str) -> Any:
    """Coerce an option assignment's value, honouring the option's own type.

    :func:`coerce_value` reads the value's shape, which is all Hyprlang text
    offers on its own. That is wrong for a string-typed option, where a
    value shaped like a Hyprlang boolean really is a string — the Norwegian
    keyboard layout is spelled ``no``, and Hyprland's Lua API answers a
    boolean there with "string type requires a string". A ``$var``
    reference still takes the shape path, which turns the marker into the
    ``LuaExpr`` the assembled output needs.
    """
    if option_type(full_key) == "string" and not has_var_marker(value):
        return value
    return coerce_value(value)


def _try_gradient(value: str) -> dict[str, Any] | None:
    """Recognise a multi-colour gradient value and convert to a structured dict.

    Single-colour values without an angle (``rgba(595959aa)``) deliberately
    return ``None`` — keeping them as strings matches what the upstream Lua
    example does, and avoids over-converting borders that don't gradient
    anyway.
    """
    try:
        g = Gradient.parse(value)
    except ValueError:
        return None
    if len(g.colors) < 2 and g.angle == 0:
        return None
    result: dict[str, Any] = {"colors": [c.to_rgba() for c in g.colors]}
    if g.angle:
        result["angle"] = g.angle
    return result


_GRADIENT_ANGLE_RE = re.compile(r"(-?\d+)\s*deg\s*$")


def _drop_zero_angle(value: str) -> str | None:
    """Reduce a single solid colour carrying a redundant ``0deg`` to a bare colour.

    Hyprland's Lua colour parser accepts a bare colour (``"0xRRGGBB"``) or a
    structured gradient table. It rejects the ``"<colour> 0deg"`` string a
    single-colour border produces (see issue #43). A real gradient needs at
    least two stops or a non-zero angle, and those already route through
    :func:`_try_gradient`, so a zero angle reaching here belongs to a plain
    solid colour. Dropping the no-op angle leaves a colour string Hyprland
    accepts, in the user's original notation.

    Returns ``None`` when *value* isn't that shape, so the caller leaves bare
    colours, paths and free text untouched.
    """
    m = _GRADIENT_ANGLE_RE.search(value)
    if m is None or int(m.group(1)) != 0:
        return None
    head = value[: m.start()].strip()
    try:
        Color.parse(head)
    except ValueError:
        return None
    return head


def _try_gradient_with_markers(s: str) -> dict[str, Any] | None:
    """Build a structured gradient table when at least one colour is a ``$var``.

    Hyprland's Lua API wants gradients as ``{colors = {...}, angle = N}`` —
    inlining a multi-colour value into a single string (``var_c1 .. " " ..
    var_c2 .. " 45deg"``) would land in the wrong API path. Parsing the
    angle and colour tokens by hand here keeps the structured shape while
    letting variable references survive as ``LuaExpr`` entries inside the
    ``colors`` list.

    Returns ``None`` if the input doesn't look like a multi-colour gradient
    or any non-variable token fails to parse as a colour — caller falls
    back to plain :func:`to_lua_expr` so we never produce mangled output.
    """
    text = s
    angle = 0
    m = _GRADIENT_ANGLE_RE.search(text)
    if m:
        angle = int(m.group(1))
        text = text[: m.start()].strip()
    tokens = text.split()
    if not tokens or (len(tokens) < 2 and angle == 0):
        return None
    colors: list[Any] = []
    for tok in tokens:
        if has_var_marker(tok):
            colors.append(to_lua_expr(tok))
        else:
            try:
                colors.append(Color.parse(tok).to_rgba())
            except ValueError:
                return None
    result: dict[str, Any] = {"colors": colors}
    if angle:
        result["angle"] = angle
    return result


def _quote_literal(s: str) -> str:
    """Quote *s* as a Lua string literal, no marker handling."""
    escaped = (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def quote_string(s: str) -> str:
    """Quote *s* as a Lua string, or render it as a Lua expression.

    Returns a plain double-quoted literal for ordinary strings; if *s*
    carries variable markers (see :data:`VAR_MARKER_OPEN`), returns the
    rendered :class:`LuaExpr.source` instead so the caller drops a live
    ``var_*`` reference (or concat chain) at the call site rather than
    quoting the marker bytes verbatim.
    """
    if has_var_marker(s):
        return to_lua_expr(s).source
    return _quote_literal(s)


def _format_key(k: str) -> str:
    """Render a table key — bare identifier when possible, ``[\"…\"]`` otherwise."""
    if _IDENT_RE.match(k) and k not in _LUA_KEYWORDS:
        return k
    return f"[{quote_string(k)}]"


def format_value(value: Any, indent: int) -> str:
    """Render *value* as Lua source at the given indentation level."""
    if isinstance(value, LuaExpr):
        return value.source
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = format(value, ".15g")
        if "." not in text and "e" not in text and "n" not in text:
            text += ".0"
        return text
    if isinstance(value, str):
        return quote_string(value)
    if isinstance(value, dict):
        return format_table(value, indent)
    if isinstance(value, (list, tuple)):
        if not value:
            return "{}"
        inner = ", ".join(format_value(v, indent + 1) for v in value)
        return "{" + inner + "}"
    raise TypeError(f"Cannot format Lua value of type {type(value).__name__}")


def format_table(table: dict[str, Any], indent: int) -> str:
    """Render a dict as a multi-line Lua table literal."""
    if not table:
        return "{}"
    inner = INDENT * (indent + 1)
    outer = INDENT * indent
    lines = ["{"]
    for k, v in table.items():
        lines.append(f"{inner}{_format_key(k)} = {format_value(v, indent + 1)},")
    lines.append(f"{outer}}}")
    return "\n".join(lines)


def split_csv(args: str) -> list[str]:
    """Split Hyprlang comma-separated arguments, trimming surrounding whitespace."""
    return [part.strip() for part in args.split(",")]


# ---------------------------------------------------------------------------
# hyprctl keyword shell-out translation
#
# Lua-mode Hyprland (0.55+) rejects the ``keyword`` IPC verb, so any
# ``exec, hyprctl keyword …`` line that worked in Hyprlang silently breaks
# after migration. The helpers here recognise the narrow shape we can
# translate cleanly and produce native ``hl.config({...})`` calls instead.
# ---------------------------------------------------------------------------


def emit_exec_cmd_call(value: str) -> str:
    # ``hl.dsp.exec_cmd`` returns a dispatcher object meant for ``hl.bind``;
    # this is the imperative form used at top level or inside an ``hl.on`` block.
    return f"hl.exec_cmd({quote_string(value)})"


def parse_hyprctl_keyword(cmd: str) -> tuple[str, str] | None:
    """Extract ``(key, value)`` from a ``hyprctl keyword KEY VALUE`` shell-out.

    Returns ``None`` unless *cmd* is a single ``hyprctl keyword`` invocation
    whose option name is section-qualified (contains ``:`` or ``.``, e.g.
    ``dwindle:smart_split``, ``general:col.inactive_border``).

    Anything else returns ``None`` and the caller falls back to the
    pass-through ``hl.exec_cmd`` / ``hl.dsp.exec_cmd`` form:

    - ``--batch`` payloads — translation would need to split the batch
      and re-thread non-keyword commands; deferred to a hand-port.
    - Top-level directive keywords (``bind``, ``monitor``, ``env``, …)
      — those have dedicated ``hl.*`` calls, not ``hl.config``.
    - Malformed shell quoting — surfaced as the original command so
      the user can see and fix the input.
    """
    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError:
        return None
    if len(tokens) < 4 or tokens[0] != "hyprctl" or tokens[1] != "keyword":
        return None
    key = tokens[2]
    if ":" not in key and "." not in key:
        return None
    return key, " ".join(tokens[3:])


# hyprctl flags that take a value (consume the next token); the rest are
# bare switches. ``--batch`` is intentionally excluded — its trailing payload
# is a ``;``-separated batch of commands, which falls outside the
# "single hyprctl call" shape we can translate.
_HYPRCTL_VALUE_FLAGS: frozenset[str] = frozenset({"--instance", "-i"})
_HYPRCTL_BARE_FLAGS: frozenset[str] = frozenset({"-j", "-r", "-q", "--quiet"})


def parse_hyprctl_dispatch(cmd: str) -> tuple[str, str] | None:
    """Extract ``(verb, args)`` from a ``hyprctl [flags] dispatch VERB [ARGS]`` shell-out.

    Returns ``None`` unless *cmd* is a single ``hyprctl ... dispatch``
    invocation that runs as one shell command (no ``&&`` / ``||`` / ``;`` /
    ``|`` / ``$(`` / backtick). Embedded use inside a larger shell command
    returns ``None`` too: there the call stays a verbatim runtime shell-out,
    since ``hyprctl dispatch`` works the same regardless of config language.

    Lua-mode Hyprland (0.55+) reparses ``hyprctl dispatch <ARG>`` as
    ``hl.dispatch(<ARG>)``, so the legacy space-separated ``dispatch VERB ARGS``
    form fails. When the verb has a known native translation, callers
    swap in an ``hl.dsp.<verb>(...)`` dispatcher to bypass the shell hop.
    """
    if any(op in cmd for op in ("&&", "||", ";", "|", "$(", "`", "\n")):
        return None
    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError:
        return None
    if not tokens or tokens[0] != "hyprctl":
        return None
    idx = 1
    while idx < len(tokens) and tokens[idx] != "dispatch":
        tok = tokens[idx]
        if tok in _HYPRCTL_BARE_FLAGS:
            idx += 1
        elif tok in _HYPRCTL_VALUE_FLAGS:
            idx += 2
        else:
            return None
    if idx >= len(tokens) or tokens[idx] != "dispatch":
        return None
    idx += 1
    if idx >= len(tokens):
        return None
    verb = tokens[idx]
    return verb, " ".join(tokens[idx + 1 :])


def emit_keyword_config_call(full_key: str, value: str, *, indent: int) -> str:
    """Render ``hl.config({KEY-AS-NESTED-TABLE = VALUE})`` for one keyword.

    ``indent`` is the column depth of the surrounding context — 0 for a
    top-level call, 1 for one sitting inside an ``hl.on`` block or a
    bind-closure body. The contained table is formatted at the same
    depth so the multi-line output drops in cleanly at the call site.
    """
    tree: dict[str, Any] = {}
    set_nested(tree, split_key(full_key), coerce_option_value(full_key, value))
    return f"hl.config({format_table(tree, indent=indent)})"


def emit_keyword_setter_closure(full_key: str, value: str) -> str:
    """Render a bind-friendly closure that sets a keyword via ``hl.config``.

    ``hl.bind`` accepts a Lua function as its dispatcher; wrapping a
    single ``hl.config`` call in one is the canonical Lua-mode
    replacement for an ``exec, hyprctl keyword …`` shell-out.
    """
    return f"function()\n{INDENT}{emit_keyword_config_call(full_key, value, indent=1)}\nend"


def translate_exec_arg(args: str, *, indent: int) -> str:
    """Render an exec argument: keyword setter when applicable, else shell-out.

    Used by both the doc-walking exec path (``indent=1`` so the result
    nests inside an ``hl.on`` block) and the one-shot static emitter
    (``indent=0`` for a stand-alone call).
    """
    keyword = parse_hyprctl_keyword(args)
    if keyword is not None:
        return emit_keyword_config_call(*keyword, indent=indent)
    return emit_exec_cmd_call(args)
