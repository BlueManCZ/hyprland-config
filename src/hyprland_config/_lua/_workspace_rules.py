"""Bidirectional Lua ↔ Hyprlang field translation for ``workspace`` rules.

Workspace rules use different field names — and in three cases, inverted
boolean sense — between Hyprland's Lua API (``hl.workspace_rule({...})``)
and its Hyprlang CSV form (``workspace = ID, key:value, …``):

==============  ================  ===================
Lua field        Hyprlang field    Notes
==============  ================  ===================
``monitor``     ``monitor``       pass-through string
``default``    ``default``       pass-through bool
``persistent``  ``persistent``    pass-through bool
``gaps_in``     ``gapsin``        scalar int or 4-tuple
``gaps_out``    ``gapsout``       scalar int or 4-tuple
``border_size`` ``bordersize``    int
``no_border``   ``border``        bool, **inverted**
``no_rounding`` ``rounding``      bool, **inverted**
``no_shadow``   ``shadow``        bool, **inverted**
``decorate``    ``decorate``      bool
``default_name`` ``defaultName``  string
``on_created_empty`` ``on-created-empty`` string (command)
``layout_opts`` ``layoutopt``     table ↔ repeated ``layoutopt:key:value``
==============  ================  ===================

``layout_opts`` is the one field that isn't 1:1: the Hyprlang form repeats
``layoutopt:key:value`` once per option (``layoutopt:direction:right``),
while the Lua form gathers them into a single ``layout_opts = {direction =
"right"}`` table. The per-field catalogue below can't express that fan-out,
so :func:`parse_layoutopt` / :func:`format_layout_opts` carry it and the two
callers special-case the field.

Unknown fields pass through unchanged in both directions so plugin-added
or future Hyprland-added properties survive a round-trip even if we
haven't catalogued them yet.

Gap values in Hyprlang form use CSS shorthand — 1, 2, 3, or 4
space-separated integers. In Lua they're either a scalar int or a
``{top, right, bottom, left}`` table with any subset of those keys
present. We map between the two faithfully:

- Hyprlang ``gapsout:5`` ↔ Lua ``gaps_out = 5``
- Hyprlang ``gapsout:5 10 5 10`` ↔ Lua ``gaps_out = {top=5, right=10, bottom=5, left=10}``

Two- and three-value Hyprlang gap forms (``5 10`` / ``5 10 5``) are
expanded to the four-key Lua table using CSS shorthand semantics, then
emitted back out in the four-value form on the next round-trip.
"""

from dataclasses import dataclass
from typing import Any, Literal

from hyprland_config._core._values import (
    HYPRLANG_FALSE_WORDS,
    HYPRLANG_TRUE_WORDS,
    parse_hyprlang_bool,
    value_to_conf,
)

WorkspaceFieldKind = Literal["string", "int", "bool", "bool_inverse", "gap"]

# Word-shaped booleans only — ``0`` / ``1`` are deliberately excluded so a
# bare digit on an unknown field still coerces to an int (see _coerce_unknown).
_BOOL_WORDS: frozenset[str] = (HYPRLANG_TRUE_WORDS | HYPRLANG_FALSE_WORDS) - {"0", "1"}


@dataclass(frozen=True, slots=True)
class WorkspaceField:
    """One entry in the workspace rule field catalogue."""

    lua_name: str
    hyprlang_name: str
    kind: WorkspaceFieldKind


WORKSPACE_FIELDS: tuple[WorkspaceField, ...] = (
    WorkspaceField("monitor", "monitor", "string"),
    WorkspaceField("default", "default", "bool"),
    WorkspaceField("persistent", "persistent", "bool"),
    WorkspaceField("gaps_in", "gapsin", "gap"),
    WorkspaceField("gaps_out", "gapsout", "gap"),
    WorkspaceField("border_size", "bordersize", "int"),
    WorkspaceField("no_border", "border", "bool_inverse"),
    WorkspaceField("no_rounding", "rounding", "bool_inverse"),
    WorkspaceField("no_shadow", "shadow", "bool_inverse"),
    WorkspaceField("decorate", "decorate", "bool"),
    WorkspaceField("default_name", "defaultName", "string"),
    WorkspaceField("on_created_empty", "on-created-empty", "string"),
)

WORKSPACE_LUA_TO_HYPRLANG: dict[str, WorkspaceField] = {f.lua_name: f for f in WORKSPACE_FIELDS}
WORKSPACE_HYPRLANG_TO_LUA: dict[str, WorkspaceField] = {
    f.hyprlang_name: f for f in WORKSPACE_FIELDS
}

# ``layoutopt`` fans out N:1 (see module docstring), so it lives outside the
# 1:1 catalogue and is handled by the two helpers below.
LAYOUTOPT_HYPRLANG_NAME = "layoutopt"
LAYOUTOPT_LUA_NAME = "layout_opts"


def _is_truthy(value: Any) -> bool:
    """Coerce Lua/Hyprlang scalar values into a bool, defaulting to False."""
    # Hyprland silently treats malformed bool fields as False; mirror that.
    return parse_hyprlang_bool(value) or False


def _format_gap_for_hyprlang(value: Any) -> str:
    """Render a Lua-side gap value (scalar or ``{t,r,b,l}`` dict) as Hyprlang.

    Scalars emit as a single integer. Dicts always emit the four-value
    form (``top right bottom left``) even when some keys are absent —
    missing sides default to ``0``, matching Hyprland's own behaviour
    when the CSS shorthand is incomplete.
    """
    if isinstance(value, dict):
        top = int(value.get("top", 0) or 0)
        right = int(value.get("right", 0) or 0)
        bottom = int(value.get("bottom", 0) or 0)
        left = int(value.get("left", 0) or 0)
        return f"{top} {right} {bottom} {left}"
    if isinstance(value, list):
        # Lua array-style table: positional.
        nums = [int(v or 0) for v in value]
        return " ".join(str(n) for n in nums)
    return str(value)


def _parse_gap_for_lua(text: str) -> int | dict[str, int]:
    """Parse a Hyprlang gap string into the matching Lua representation.

    Single value → ``int``. Two, three, or four values → ``{top, right,
    bottom, left}`` table, expanding via CSS shorthand:

    - 2 values: ``vertical horizontal`` → ``{top=v, right=h, bottom=v, left=h}``
    - 3 values: ``top horizontal bottom`` → ``{top=t, right=h, bottom=b, left=h}``
    - 4 values: ``top right bottom left`` (literal)

    Returns the scalar form for single-value strings so the emitted Lua
    stays compact (``gaps_in = 5`` vs. ``gaps_in = {top=5, ...}``) and
    the round-trip is stable for the common case.
    """
    parts = [p for p in text.strip().split() if p]
    nums: list[int] = []
    for p in parts:
        try:
            nums.append(int(p))
        except ValueError:
            try:
                nums.append(int(float(p)))
            except ValueError:
                nums.append(0)
    if len(nums) == 1:
        return nums[0]
    if len(nums) == 2:
        v, h = nums
        return {"top": v, "right": h, "bottom": v, "left": h}
    if len(nums) == 3:
        t, h, b = nums
        return {"top": t, "right": h, "bottom": b, "left": h}
    if len(nums) >= 4:
        return {"top": nums[0], "right": nums[1], "bottom": nums[2], "left": nums[3]}
    return 0


def lua_field_to_hyprlang(lua_name: str, value: Any) -> tuple[str, str]:
    """Translate one Lua-side ``hl.workspace_rule`` field to its Hyprlang ``key:value`` form.

    Returns ``(hyprlang_name, hyprlang_value_text)``. Unknown fields pass
    through unchanged so plugin/future-Hyprland properties survive the
    round-trip — the value is stringified but otherwise untouched.
    """
    field = WORKSPACE_LUA_TO_HYPRLANG.get(lua_name)
    if field is None:
        return lua_name, value_to_conf(value)

    if field.kind == "bool":
        return field.hyprlang_name, "true" if _is_truthy(value) else "false"
    if field.kind == "bool_inverse":
        return field.hyprlang_name, "false" if _is_truthy(value) else "true"
    if field.kind == "gap":
        return field.hyprlang_name, _format_gap_for_hyprlang(value)
    if field.kind == "int":
        return field.hyprlang_name, str(int(value))
    return field.hyprlang_name, value_to_conf(value)


def hyprlang_field_to_lua(hyprlang_name: str, value: str) -> tuple[str, Any]:
    """Translate one Hyprlang ``key:value`` field to its Lua-side counterpart.

    Returns ``(lua_name, lua_value)``. Unknown fields pass through with
    a best-effort scalar coercion (numbers → int/float, ``true``/``false``
    → bool, anything else → string) so the emitted Lua remains a valid
    table value.
    """
    field = WORKSPACE_HYPRLANG_TO_LUA.get(hyprlang_name)
    if field is None:
        return hyprlang_name, _coerce_unknown(value)

    if field.kind == "bool":
        return field.lua_name, _is_truthy(value)
    if field.kind == "bool_inverse":
        return field.lua_name, not _is_truthy(value)
    if field.kind == "gap":
        return field.lua_name, _parse_gap_for_lua(value)
    if field.kind == "int":
        try:
            return field.lua_name, int(value.strip())
        except (TypeError, ValueError):
            return field.lua_name, value
    return field.lua_name, value


def parse_layoutopt(payload: str) -> tuple[str, Any] | None:
    """Parse one Hyprlang ``layoutopt:`` payload (the ``key:value`` after the
    leading ``layoutopt:``) into a ``(key, lua_value)`` pair for the
    ``layout_opts`` table.

    Returns ``None`` when the payload has no inner ``:`` separator, which
    Hyprland itself rejects as a malformed rule.
    """
    key, sep, value = payload.partition(":")
    if not sep:
        return None
    return key.strip(), _coerce_unknown(value.strip())


def format_layout_opts(opts: dict[str, Any]) -> list[str]:
    """Render a Lua ``layout_opts`` table as Hyprlang ``layoutopt:key:value`` tokens."""
    return [f"{LAYOUTOPT_HYPRLANG_NAME}:{key}:{value_to_conf(opts[key])}" for key in sorted(opts)]


def _coerce_unknown(text: str) -> Any:
    """Best-effort coercion for a pass-through Hyprlang field value."""
    stripped = text.strip()
    # Bare ``0``/``1`` look like ints for an unknown field — only treat
    # word-shaped booleans as bool here, ints fall through to the int branch.
    if stripped.lower() in _BOOL_WORDS:
        return parse_hyprlang_bool(stripped)
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        pass
    return stripped
