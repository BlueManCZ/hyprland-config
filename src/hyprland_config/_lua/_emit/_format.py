"""Lua source-formatting primitives and value coercion.

Used by every emitter so they produce consistent output: scalar coercion
(Hyprlang value string → Lua-ready Python value), Lua string/key/table
formatting, and a handful of helpers for ``exec, hyprctl keyword …``
shell-out translation.
"""

import re
import shlex
from typing import Any

from hyprland_config._core._types import Gradient

INDENT = "    "

_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

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
    - the case-insensitive words ``true``/``false`` become booleans,
    - multi-colour gradients (``rgba(…) rgba(…) 45deg``) become a structured
      ``{colors = {…}, angle = N}`` dict, matching the form Hyprland's Lua API
      uses in the official example,
    - everything else (single colours, paths, vec2, free text) stays a string.
    """
    stripped = s.strip()
    if _INT_RE.match(stripped):
        return int(stripped)
    if _FLOAT_RE.match(stripped):
        return float(stripped)
    if stripped.lower() == "true":
        return True
    if stripped.lower() == "false":
        return False
    gradient = _try_gradient(stripped)
    if gradient is not None:
        return gradient
    return s


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


def quote_string(s: str) -> str:
    """Quote *s* as a Lua double-quoted string literal."""
    escaped = (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _format_key(k: str) -> str:
    """Render a table key — bare identifier when possible, ``[\"…\"]`` otherwise."""
    if _IDENT_RE.match(k) and k not in _LUA_KEYWORDS:
        return k
    return f"[{quote_string(k)}]"


def format_value(value: Any, indent: int) -> str:
    """Render *value* as Lua source at the given indentation level."""
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
    """``hl.exec_cmd("…")`` — the imperative form, not the dispatcher.

    ``hl.dsp.exec_cmd`` returns a dispatcher object meant for ``hl.bind``;
    this is the bare call used at top level or inside an ``hl.on`` block.
    """
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
    is handled by :func:`rewrite_hyprctl_dispatch_in_shell` instead.

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
    set_nested(tree, split_key(full_key), coerce_value(value))
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
