"""Flatten an ``hl.config({...})`` table back into Hyprlang assignments.

The emitter's ``hl.config`` payload is a nested Lua table; we walk it
depth-first and emit one :class:`Assignment` per leaf, with the
``full_key`` reconstructed by joining the nesting path with ``:``. The
``col.X`` sub-namespace gets the dot back rather than a third colon
level so the round-trip with the Hyprlang parser is symmetric.
"""

from typing import Any

from hyprland_config._core._model import Assignment, Document
from hyprland_config._lua._emit._format import DOT_PREFIX_KEYS


def emit_config_assignments(
    doc: Document,
    tree: dict[str, Any],
    prefix: str = "",
    *,
    source: str = "",
) -> None:
    """Flatten an ``hl.config({...})`` tree into Assignment nodes.

    Recurses through nested dicts so ``{ general = { gaps_in = 5 } }``
    becomes ``Assignment(full_key="general:gaps_in", value="5")``. Special-
    cases the ``col`` sub-namespace (``general.col.inactive_border``) so
    its leaves come out as ``general:col.inactive_border`` — matching the
    Hyprlang convention rather than a third colon level.

    Gradient table values (``{ colors = {...}, angle = N }``) and Vec2
    array values (``{ x, y }``) get reassembled into their Hyprlang
    string form so downstream consumers see the same shape they would
    for a parsed ``.conf``.
    """
    for key, value in tree.items():
        if (
            prefix
            and key in DOT_PREFIX_KEYS
            and isinstance(value, dict)
            and not _looks_like_gradient(value)
        ):
            for leaf_key, leaf_value in value.items():
                _add_leaf(doc, f"{prefix}{key}.{leaf_key}", leaf_value, source=source)
            continue

        full_key = f"{prefix}{key}" if prefix else key
        if isinstance(value, dict) and not _looks_like_gradient(value):
            emit_config_assignments(doc, value, prefix=full_key + ":", source=source)
        else:
            _add_leaf(doc, full_key, value, source=source)


def _add_leaf(doc: Document, full_key: str, value: Any, *, source: str = "") -> None:
    """Render a leaf value (gradient / list / scalar) to one Assignment line."""
    if isinstance(value, dict) and _looks_like_gradient(value):
        _add_assignment(doc, full_key, _gradient_to_hyprlang(value), source=source)
    elif isinstance(value, list):
        _add_assignment(doc, full_key, _list_to_hyprlang(value), source=source)
    else:
        _add_assignment(doc, full_key, scalar_to_hyprlang(value), source=source)


def _add_assignment(doc: Document, full_key: str, value: str, *, source: str = "") -> None:
    # ``key`` carries the whole colon path, not the leaf: these lines sit at
    # top level with no enclosing section, which is the flat Hyprlang shape
    # (``key == full_key``). A leaf-only key would re-render as a bare
    # ``border_size = 2`` the moment anything calls ``update_raw``.
    doc.lines.append(
        Assignment(
            raw=f"{full_key} = {value}\n",
            key=full_key,
            value=value,
            full_key=full_key,
            source_name=source,
        )
    )


def _looks_like_gradient(value: dict[str, Any]) -> bool:
    """Distinguish a gradient table from any other nested config dict."""
    if "colors" not in value:
        return False
    colors = value["colors"]
    return isinstance(colors, list)


def _gradient_to_hyprlang(value: dict[str, Any]) -> str:
    """Render ``{ colors = {...}, angle = N }`` back to Hyprlang text."""
    parts = [str(c) for c in value.get("colors", [])]
    angle = value.get("angle")
    if angle is not None:
        parts.append(f"{angle}deg")
    return " ".join(parts)


def _list_to_hyprlang(value: list[Any]) -> str:
    """Render a list value (vec2, bezier points) back to a space-joined string."""
    parts: list[str] = []
    for item in value:
        if isinstance(item, list):
            parts.append(" ".join(scalar_to_hyprlang(v) for v in item))
        else:
            parts.append(scalar_to_hyprlang(item))
    return " ".join(parts)


def scalar_to_hyprlang(value: Any) -> str:
    """Render one Lua scalar value as Hyprlang text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return format_number(value)
    if value is None:
        return ""
    return str(value)


def format_number(n: int | float) -> str:
    """Format ``n`` as integer when it's an integral float, else as-is."""
    if isinstance(n, float) and n.is_integer():
        return str(int(n))
    return str(n)
