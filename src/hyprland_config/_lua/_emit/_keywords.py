"""Static keyword emitters: env / monitor / bezier / animation / gesture / permission / plugin.

Each function takes the Hyprlang ``value`` string for one ``key = value``
line and returns a one-line ``hl.*`` Lua snippet. Used by the document
walker and by the single-line public ``emit_keyword_line`` API.
"""

from typing import Any

from hyprland_config._core._values import parse_hyprlang_bool
from hyprland_config._lua._emit._format import (
    INDENT,
    coerce_value,
    format_table,
    format_value,
    quote_string,
    split_csv,
)
from hyprland_config._lua._workspace_rules import parse_gap_for_lua


def emit_env(args: str) -> str:
    """``env = NAME, VALUE`` → ``hl.env("NAME", "VALUE")``."""
    parts = split_csv(args)
    name = parts[0] if parts else ""
    value = parts[1] if len(parts) >= 2 else ""
    return f"hl.env({quote_string(name)}, {quote_string(value)})"


def emit_monitor(args: str) -> str:
    """``monitor = OUTPUT, MODE, POSITION, SCALE [, KEY, VALUE]…`` → ``hl.monitor({...})``.

    Trailing arguments come as space-separated ``KEY, VALUE`` pairs (e.g.
    ``transform, 3``, ``bitdepth, 10``, ``mirror, DP-2``, ``vrr, 1``). Each
    pair becomes a typed Lua field. An odd-length trailing tail (a single
    KEY with no value) is rare but we surface it as a comment-style entry
    so the user can see what got dropped.

    Hyprlang's short forms put a verb where the mode goes:

    - ``OUTPUT, disable`` (or ``disabled``) maps to the Lua API's
      ``disabled = true`` field (the Lua side rejects ``mode = "disable"``
      — confirmed against Hyprland 0.55+).
    - ``OUTPUT, transform, N`` and ``OUTPUT, addreserved, T, B, L, R``
      change one field of the output's rule. ``hl.monitor`` merges into an
      existing rule for the same output, so they emit just that field.

    A full line conversely emits an explicit ``disabled = false`` — see below.
    """
    parts = split_csv(args)
    table: dict[str, Any] = {}
    # Always emit ``output``, even when the name field is empty. The catch-all
    # rule ``monitor = , preferred, auto, 1`` (no output name) is common, and
    # Hyprland's Lua ``hl.monitor`` rejects a table without ``output`` ("output
    # field is required and should be a string"). An empty name becomes
    # ``output = ""`` — the explicit form the compositor accepts.
    if parts:
        table["output"] = parts[0]
    verb = parts[1].strip().lower() if len(parts) >= 2 else ""
    if verb in ("disable", "disabled"):
        table["disabled"] = True
        return f"hl.monitor({format_table(table, indent=0)})"
    if verb == "transform":
        if len(parts) < 3:
            return f"-- malformed monitor: {args}"
        table["transform"] = coerce_value(parts[2])
        return f"hl.monitor({format_table(table, indent=0)})"
    if verb == "addreserved":
        reserved = _reserved_table(parts[2:])
        if reserved is None:
            return f"-- malformed monitor: {args}"
        table["reserved"] = reserved
        return f"hl.monitor({format_table(table, indent=0)})"
    # A full line means "this output, configured and on". Legacy Hyprlang
    # re-enables a previously-disabled output implicitly whenever it sees a full
    # line, but the Lua ``hl.monitor`` API is additive — a ``disabled = true``
    # from an earlier call sticks until explicitly cleared. A live re-enable that
    # omits the field therefore leaves the output dark (it only comes back on a
    # full config reload). Emit ``disabled = false`` to reproduce the legacy
    # implicit-enable semantics on live apply.
    table["disabled"] = False
    if len(parts) >= 2:
        table["mode"] = parts[1]
    if len(parts) >= 3:
        table["position"] = parts[2]
    if len(parts) >= 4:
        table["scale"] = coerce_value(parts[3])
    extras = parts[4:]
    i = 0
    while i < len(extras) - 1:
        key = extras[i].strip()
        value = extras[i + 1].strip()
        if key:
            table[key] = _monitor_field_value(key, value)
        i += 2
    if i < len(extras):
        # Dangling odd-length tail — leave a marker so it's not silently dropped.
        table["__unparsed_extra"] = extras[i]
    return f"hl.monitor({format_table(table, indent=0)})"


def emit_monitorv2(fields: dict[str, str]) -> str:
    """A ``monitorv2 { … }`` block's fields → ``hl.monitor({...})``.

    The block names the same rule fields as a ``monitor`` line, one per
    line. Hyprland builds a fresh rule from each block, so like a full line
    it emits ``disabled = false`` unless the block disables the output.
    ``addreserved = T, B, L, R`` becomes the ``reserved`` table.
    """
    table: dict[str, Any] = {"output": fields.get("output", "")}
    table["disabled"] = parse_hyprlang_bool(fields.get("disabled", "false")) is True
    for key, value in fields.items():
        if key in ("output", "disabled"):
            continue
        if key == "addreserved":
            reserved = _reserved_table(split_csv(value))
            table["reserved"] = reserved if reserved is not None else value
        elif key in ("mode", "position"):
            table[key] = value
        else:
            table[key] = _monitor_field_value(key, value)
    return f"hl.monitor({format_table(table, indent=0)})"


# Lua-only ``hl.monitor`` fields holding a ``{top, right, bottom, left}``
# table. A Lua config read back writes them into a ``monitor`` line as
# ``reserved, T R B L``; see :func:`monitor_value`.
_MONITOR_GAP_FIELDS = frozenset({"reserved", "reserved_area"})


def _monitor_field_value(key: str, value: str) -> Any:
    if key in _MONITOR_GAP_FIELDS:
        return parse_gap_for_lua(value)
    return coerce_value(value)


def _reserved_table(values: list[str]) -> dict[str, int] | None:
    """Hyprlang's ``addreserved`` values, ordered top, bottom, left, right, as a Lua table.

    The Lua ``reserved`` field takes CSS order (top, right, bottom, left)
    by name. ``None`` unless *values* holds four integers.
    """
    try:
        top, bottom, left, right = (int(v) for v in values)
    except ValueError:
        return None
    return {"top": top, "right": right, "bottom": bottom, "left": left}


def emit_bezier(args: str) -> str:
    """``bezier = NAME, x0, y0, x1, y1`` → ``hl.curve(NAME, {type="bezier", …})``."""
    parts = split_csv(args)
    if len(parts) < 5:
        return f"-- malformed bezier: {args}"
    name = parts[0]
    p1x, p1y = coerce_value(parts[1]), coerce_value(parts[2])
    p2x, p2y = coerce_value(parts[3]), coerce_value(parts[4])
    point1 = f"{{{format_value(p1x, 0)}, {format_value(p1y, 0)}}}"
    point2 = f"{{{format_value(p2x, 0)}, {format_value(p2y, 0)}}}"
    return (
        f'hl.curve({quote_string(name)}, {{ type = "bezier", points = {{ {point1}, {point2} }} }})'
    )


def emit_animation(args: str) -> str:
    """``animation = NAME, ONOFF, SPEED, CURVE [, STYLE]`` → ``hl.animation({…})``."""
    parts = split_csv(args)
    if not parts:
        return f"-- malformed animation: {args}"
    table: dict[str, Any] = {"leaf": parts[0]}
    if len(parts) >= 2:
        table["enabled"] = parse_hyprlang_bool(parts[1]) is True
    if len(parts) >= 3:
        table["speed"] = coerce_value(parts[2])
    if len(parts) >= 4 and parts[3]:
        table["bezier"] = parts[3]
    if len(parts) >= 5 and parts[4]:
        table["style"] = parts[4]
    return f"hl.animation({format_table(table, indent=0)})"


def emit_gesture(args: str) -> str:
    """``gesture = FINGERS, DIRECTION, ACTION [, mods=…]`` → ``hl.gesture({...})``."""
    parts = split_csv(args)
    if len(parts) < 3:
        return f"-- malformed gesture: {args}"
    table: dict[str, Any] = {
        "fingers": coerce_value(parts[0]),
        "direction": parts[1],
        "action": parts[2],
    }
    # Trailing tokens are k:v rule fields (e.g. ``mods:SUPER``, ``scale:0.5``).
    for token in parts[3:]:
        key, sep, value = token.partition(":")
        if sep:
            table[key.strip()] = coerce_value(value.strip())
    return f"hl.gesture({format_table(table, indent=0)})"


def emit_permission(args: str) -> str:
    """``permission = REGEX, TYPE, ACTION`` → ``hl.permission("REGEX", "TYPE", "ACTION")``."""
    parts = split_csv(args)
    if len(parts) < 3:
        return f"-- malformed permission: {args}"
    return (
        f"hl.permission({quote_string(parts[0])}, "
        f"{quote_string(parts[1])}, {quote_string(parts[2])})"
    )


def emit_plugin_load(value: str) -> str | None:
    """``plugin = /path/to.so`` → ``hl.plugin.load("/path/to.so")``.

    ``hl.plugin`` is a namespace table, not a function; calling
    ``hl.plugin(...)`` would raise "attempt to call a table value" at
    runtime.
    """
    path = value.strip()
    if not path:
        return None
    return f"hl.plugin.load({quote_string(path)})"


def format_exec_block(event: str, commands: list[str]) -> str:
    lines = [f"hl.on({quote_string(event)}, function()"]
    for cmd in commands:
        lines.append(f"{INDENT}{cmd}")
    lines.append("end)\n")
    return "\n".join(lines)
