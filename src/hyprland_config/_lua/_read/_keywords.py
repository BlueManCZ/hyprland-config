"""Per-keyword shape converters — Lua call args back to Hyprlang text.

Each converter takes the recorded ``hl.<keyword>`` table and returns
the Hyprlang CSV string the original config would have written. The
result feeds into a :class:`Keyword` line on the synthesised Document
so that consumers see the same line shape regardless of which side
wrote it.
"""

from typing import Any

from hyprland_config._core._model import Assignment, Document, Rule, SectionClose, SectionOpen
from hyprland_config._lua._read._config import format_number, scalar_to_hyprlang
from hyprland_config._lua._workspace_rules import (
    LAYOUTOPT_LUA_NAME,
    format_layout_opts,
    lua_field_to_hyprlang,
)


def monitor_value(t: dict[str, Any]) -> str:
    """Reassemble ``hl.monitor({...})`` into ``output, mode, position, scale[, k, v...]``.

    ``disabled = true`` is the Lua-side counterpart of Hyprlang's
    ``monitor = OUTPUT, disable`` short-form; we round-trip it back to
    the legacy shape so line-oriented consumers see the canonical form
    regardless of which side wrote it.
    """
    if t.get("disabled") is True:
        return f"{t.get('output', '')}, disable"
    parts = [
        str(t.get("output", "")),
        str(t.get("mode", "preferred")),
        str(t.get("position", "auto")),
        format_number(t.get("scale", 1)),
    ]
    excluded = {"output", "mode", "position", "scale", "disabled"}
    extras = {k: v for k, v in t.items() if k not in excluded}
    for key in sorted(extras):
        parts.append(key)
        parts.append(scalar_to_hyprlang(extras[key]))
    return ", ".join(parts)


def bezier_value(name: Any, t: dict[str, Any]) -> str:
    """``hl.curve("name", { type=bezier, points={{a,b},{c,d}} })`` → ``name, a, b, c, d``."""
    points: list[Any] = t.get("points", [])
    flat: list[str] = [str(name)]
    for pair in points:
        if isinstance(pair, list):
            flat.extend(scalar_to_hyprlang(p) for p in pair)
    return ", ".join(flat)


def animation_value(t: dict[str, Any]) -> str:
    """``hl.animation({leaf, enabled, speed, bezier, style})`` → CSV form."""
    parts = [str(t.get("leaf", ""))]
    enabled = t.get("enabled", True)
    # Canonical Hyprlang booleans are ``true``/``false`` (project-wide
    # convention since v0.4.5); animation also accepts ``1``/``0`` and a
    # handful of synonyms, but we emit the canonical token.
    parts.append("true" if enabled else "false")
    speed = t.get("speed")
    if speed is not None:
        parts.append(format_number(speed))
    bezier = t.get("bezier") or t.get("spring") or "default"
    parts.append(str(bezier))
    if t.get("style"):
        parts.append(str(t["style"]))
    return ", ".join(parts)


def rule_to_node(kind: str, t: dict[str, Any]) -> Rule:
    """Build a structured :class:`Rule` node from an ``hl.window_rule``
    or ``hl.layer_rule`` table.

    The Lua table mirrors the Rule shape one-to-one: ``name`` and
    ``enabled`` map to the same-named fields; ``match`` becomes the
    matcher list; every other key is an effect. Sorted iteration over
    the effect/matcher keys keeps emission deterministic — the Lua
    wrapper preserves user authoring order, but that's unstable across
    edits, so sorting on the way back to a Document means downstream
    diffs reflect semantic changes only.
    """
    name_value = t.get("name")
    name = name_value.strip() if isinstance(name_value, str) else ""
    enabled = t.get("enabled") is not False

    matchers: list[tuple[str, str]] = []
    if isinstance(t.get("match"), dict):
        for mkey in sorted(t["match"]):
            matchers.append((mkey, scalar_to_hyprlang(t["match"][mkey])))

    effects: list[tuple[str, str]] = []
    for key in sorted(t):
        if key in ("match", "name", "enabled"):
            continue
        effects.append((key, _effect_args_from_lua(t[key])))

    return Rule(
        raw="",
        kind=kind,
        name=name,
        enabled=enabled,
        matchers=matchers,
        effects=effects,
    )


def _effect_args_from_lua(value: Any) -> str:
    """Translate a Lua-side effect value to its Hyprlang args string.

    Bool effects in Lua are ``true``/``false``; Hyprland 0.53+ requires
    the explicit ``on``/``off`` token so the Hyprlang serializer can
    round-trip without losing the value. Numbers and strings pass
    through :func:`scalar_to_hyprlang` unchanged.
    """
    if value is True:
        return "on"
    if value is False:
        return "off"
    return scalar_to_hyprlang(value)


def workspace_value(t: dict[str, Any]) -> str:
    """``hl.workspace_rule({workspace, monitor, default, ...})`` → Hyprlang CSV.

    Field names and a handful of boolean senses differ between the two
    forms (Lua ``no_border = true`` ↔ Hyprlang ``border:false``);
    :func:`lua_field_to_hyprlang` carries the catalogue. Unknown keys
    pass through unchanged so plugin / future-Hyprland fields survive
    the round-trip.
    """
    ws = t.get("workspace", "")
    parts = [scalar_to_hyprlang(ws)]
    for key in sorted(t):
        if key == "workspace":
            continue
        if key == LAYOUTOPT_LUA_NAME and isinstance(t[key], dict):
            parts.extend(format_layout_opts(t[key]))
            continue
        name, value = lua_field_to_hyprlang(key, t[key])
        parts.append(f"{name}:{value}")
    return ", ".join(parts)


def gesture_value(t: dict[str, Any]) -> str:
    """``hl.gesture({fingers, direction, action, ...})`` → CSV form."""
    fingers = t.get("fingers", 0)
    direction = t.get("direction", "")
    action = t.get("action", "")
    parts = [format_number(fingers), str(direction), str(action)]
    for key in sorted(t):
        if key in {"fingers", "direction", "action"}:
            continue
        parts.append(f"{key}:{scalar_to_hyprlang(t[key])}")
    return ", ".join(parts)


def emit_device(doc: Document, t: dict[str, Any], *, source: str = "") -> None:
    """``hl.device({name, ...})`` → emit a Hyprlang ``device { ... }`` block.

    The Document model already understands the section form, and that
    keeps the round-trip with the emitter symmetric. A regular CSV-style
    keyword wouldn't work because Hyprlang has no scalar-form ``device``.
    """
    doc.lines.append(SectionOpen(raw="device {\n", name="device", source_name=source))
    for key in sorted(t):
        value = t[key]
        rendered = scalar_to_hyprlang(value)
        doc.lines.append(
            Assignment(
                raw=f"    {key} = {rendered}\n",
                key=key,
                value=rendered,
                full_key=f"device:{key}",
                source_name=source,
            )
        )
    doc.lines.append(SectionClose(raw="}\n", source_name=source))
