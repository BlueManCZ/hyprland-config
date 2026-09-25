"""Reverse-map ``hl.bind(...)`` / ``hl.unbind(...)`` to Hyprlang ``bind = …`` lines.

Picks the right ``bind`` variant (``bind`` / ``binde`` / ``bindml`` / …)
based on the flag table, formats the key combo, and translates the
dispatcher via :mod:`._dispatchers`. Mirrors :meth:`BindData.to_line`
on the output shape so consumers see the same canonical form regardless
of which side wrote the file.
"""

from typing import Any

from hyprland_config._core._bind import BIND_FLAG_MAP, has_description_flag
from hyprland_config._lua._read._dispatchers import dispatcher_to_hyprlang

# Lua flag fields (third arg to hl.bind) → Hyprlang bind-keyword suffix
# char. Inverse of ``_bind.BIND_FLAG_MAP``; combinations like
# "repeating + locked" → "bindel" come out naturally because we sort the
# suffix chars before joining.
_FLAG_TO_SUFFIX = {flag: ch for ch, flag in BIND_FLAG_MAP.items()}


def bind_value(args: list[Any]) -> tuple[str, str] | None:
    """Render ``hl.bind(keys, dispatcher, flags?)`` to ``(bind_type, value)``.

    Mirrors the value-returning shape of :func:`monitor_value` /
    :func:`animation_value` — pairs with :func:`unbind_value` for the
    reverse direction. Returns ``None`` when *args* is empty. Output
    mirrors :meth:`BindData.to_line`: mods are space-joined, and the
    trailing comma is omitted when ``arg`` is empty (``bindm`` rejects a
    trailing comma — other variants tolerate either form but we keep the
    canonical shape across the board).
    """
    if not args:
        return None
    keys = args[0]
    dispatcher = args[1] if len(args) >= 2 else None
    flags = args[2] if len(args) >= 3 and isinstance(args[2], dict) else {}

    bind_type, description = _classify_bind(flags)
    mods, key = _split_keys(str(keys))
    dispatcher_str, arg_str = dispatcher_to_hyprlang(dispatcher)

    # ``bindd`` carries the description as the third comma-separated field,
    # before the dispatcher; other variants put the dispatcher third.
    if has_description_flag(bind_type):
        parts = [" ".join(mods), key, description, dispatcher_str]
    else:
        parts = [" ".join(mods), key, dispatcher_str]

    value = ", ".join(parts)
    if arg_str:
        value = f"{value}, {arg_str}"
    return bind_type, value


def _classify_bind(flags: dict[str, Any]) -> tuple[str, str]:
    """Pick the right ``bind`` variant ('bind' / 'binde' / 'bindml' / …)."""
    description_value = flags.get("description")
    has_description = isinstance(description_value, str)
    description = description_value if has_description else ""
    suffix_chars: list[str] = []
    for flag, suffix in _FLAG_TO_SUFFIX.items():
        if flags.get(flag):
            suffix_chars.append(suffix)
    if has_description:
        suffix_chars.append("d")
    suffix_chars.sort()
    return "bind" + "".join(suffix_chars), description


def _split_keys(keys: str) -> tuple[list[str], str]:
    """Split a Lua key combo (``"SUPER + Q"``) into Hyprlang ``mods, key``."""
    parts = [p.strip() for p in keys.split("+")]
    parts = [p for p in parts if p]
    if not parts:
        return [], ""
    return parts[:-1], parts[-1]


def unbind_value(args: list[Any]) -> str:
    """Render ``hl.unbind("MODS + KEY")`` back to the Hyprlang ``MODS, KEY`` form.

    Hyprlang's canonical unbind shape is ``unbind = SUPER SHIFT, Q``
    (space-joined mods, comma between mods and key). A raw passthrough
    of the ``"SUPER + Q"`` combo string would lose that split.
    """
    if not args:
        return ""
    mods, key = _split_keys(str(args[0]))
    if not key:
        return ""
    if mods:
        return f"{' '.join(mods)}, {key}"
    # Bare ``unbind = , KEY`` keeps the leading comma so consumers that
    # split on the first comma still see a two-part value.
    return f", {key}"
