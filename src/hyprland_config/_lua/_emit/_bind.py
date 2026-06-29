"""Bind family emitters — ``bind`` / ``binde`` / ``bindm`` / ``bindd`` / … → ``hl.bind(...)``.

Suffix characters after ``bind`` map to flag fields on the Lua-side
``hl.bind`` call (``e``→repeating, ``l``→locked, ``m``→mouse, ``r``→release,
``n``→non_consuming, ``t``→transparent, ``i``→ignore_mods). The ``d``
suffix carries an extra description string between the key and the
dispatcher.

The dispatcher itself is translated via :mod:`._dispatchers` so the
config-side bind emitter and the runtime ``dispatch_to_lua`` API
produce the same Lua call shape.
"""

from typing import Any

from hyprland_config._core._bind import BIND_FLAG_MAP, BindData
from hyprland_config._hyprlang._bind import parse_bind_line
from hyprland_config._lua._emit._dispatchers import translate_dispatcher
from hyprland_config._lua._emit._format import VAR_MARKER_OPEN, format_table, quote_string

# Modifier substrings → canonical Lua token. Hyprland's legacy Hyprlang parser
# (``stringToModMask``) uppercased the whole mods field and matched each name
# as a *substring*, so concatenated (``SUPERSHIFT``) and mixed-case (``Alt``)
# forms all resolved to the same modmask. Hyprland's Lua ``hl.bind`` instead
# requires exact uppercase tokens (``modFromSv``) and reads anything else as a
# keysym, so migration has to decompose the legacy forms into canonical tokens.
_MOD_ALIASES: tuple[tuple[str, str], ...] = (
    ("SUPER", "SUPER"),
    ("WIN", "SUPER"),
    ("LOGO", "SUPER"),
    ("MOD4", "SUPER"),
    ("META", "SUPER"),
    ("CONTROL", "CTRL"),
    ("CTRL", "CTRL"),
    ("ALT", "ALT"),
    ("MOD1", "ALT"),
    ("SHIFT", "SHIFT"),
    ("CAPS", "CAPS"),
    ("MOD2", "MOD2"),
    ("MOD3", "MOD3"),
    ("MOD5", "MOD5"),
)
# Conventional emit order — purely cosmetic, the modmask is order-independent.
_MOD_ORDER: tuple[str, ...] = ("SUPER", "CTRL", "ALT", "SHIFT", "CAPS", "MOD2", "MOD3", "MOD5")


def is_modifier_token(token: str) -> bool:
    """Whether *token* names one or more bind modifiers (``SUPER``, ``SUPERSHIFT``).

    Matches the substring rule of legacy ``stringToModMask`` used by
    :func:`_normalize_mods`, so concatenated and mixed-case forms count too.
    """
    upper = token.upper()
    return any(name in upper for name, _ in _MOD_ALIASES)


def _normalize_mods(mods: list[str]) -> list[str]:
    """Decompose Hyprlang modifier tokens into canonical Lua mod tokens.

    Each whitespace-split token is matched against :data:`_MOD_ALIASES` by
    substring (mirroring legacy ``stringToModMask``), so ``SUPERSHIFT`` →
    ``["SUPER", "SHIFT"]`` and ``Alt`` → ``["ALT"]``. Tokens carrying a ``$var``
    reference (already wrapped in :data:`VAR_MARKER_OPEN` sentinels by
    ``expand_value_lua``) are passed through untouched, as are tokens that match
    no known modifier — preserving the user's intent rather than dropping them.
    """
    result: list[str] = []
    for token in mods:
        if not token or VAR_MARKER_OPEN in token or "$" in token:
            result.append(token)
            continue
        upper = token.upper()
        found = {canonical for name, canonical in _MOD_ALIASES if name in upper}
        decomposed = [m for m in _MOD_ORDER if m in found] if found else [token]
        for mod in decomposed:
            if mod not in result:
                result.append(mod)
    return result


def _bind_flags_from_suffix(suffix: str) -> dict[str, bool] | None:
    """Map suffix characters (after stripping ``d`` if present) to flag fields.

    ``d`` is handled separately by the caller (it adds a ``description``
    field and shifts the positional layout); ``s`` and ``p`` aren't in
    ``BIND_FLAG_MAP`` because they have no documented Lua equivalent, so
    a bind that uses them returns ``None`` and lands in the
    manual-conversion block.
    """
    flags: dict[str, bool] = {}
    for ch in suffix:
        flag = BIND_FLAG_MAP.get(ch)
        if flag is None:
            return None
        flags[flag] = True
    return flags


def _format_key_combo(mods: list[str], key: str) -> str:
    """Format a Hyprlang ``MODS, KEY`` pair as a Lua ``"SUPER + Q"`` string."""
    parts = [m for m in _normalize_mods(mods) if m]
    if key:
        parts.append(key)
    return " + ".join(parts)


def _parse_bindd_args(bind_type: str, args: str) -> tuple[BindData, str] | None:
    """Parse ``bindd``-family args (with the extra description field).

    ``bindd``-style binds carry an extra description string between the key
    and the dispatcher: ``MODS, KEY, DESCRIPTION, DISPATCHER [, ARG]``.
    Returns the bind plus the description, or ``None`` if the line can't be
    decoded (fewer than four comma-separated parts).
    """
    parts = [p.strip() for p in args.split(",", 4)]
    if len(parts) < 4:
        return None
    mods_str, key_name, description, dispatcher = parts[0], parts[1], parts[2], parts[3]
    arg = parts[4] if len(parts) > 4 else ""
    bind = BindData(
        bind_type=bind_type,
        mods=mods_str.split() if mods_str else [],
        key=key_name,
        dispatcher=dispatcher,
        arg=arg,
    )
    return bind, description


def emit_unbind(args: str) -> str | None:
    """Emit ``hl.unbind("MODS + KEY")`` from a Hyprlang ``unbind = MODS, KEY``.

    Returns ``None`` for malformed input (no comma, empty key) so the
    caller drops the line into the manual-conversion block rather than
    producing invalid Lua. Whitespace around mods/key is stripped; bare
    ``KEY`` (no modifier) is preserved.
    """
    mods_str, sep, key_name = args.partition(",")
    # ``unbind = , F1`` is technically legal (no modifier). Without a
    # comma at all we can't distinguish "missing key" from "missing
    # mods", so we refuse.
    if not sep:
        return None
    key_name = key_name.strip()
    if not key_name:
        return None
    mods = mods_str.split() if mods_str.strip() else []
    return f"hl.unbind({quote_string(_format_key_combo(mods, key_name))})"


def emit_bind(bind_type: str, args: str) -> str | None:
    """Emit a ``hl.bind(...)`` call, or ``None`` if it needs manual review.

    Reasons to bail out (return ``None`` so the caller drops it in the
    manual-conversion block) include: an unsupported flag suffix, an
    unrecognised dispatcher, or a malformed line the bind parser can't decode.
    """
    suffix = bind_type.removeprefix("bind")
    has_description = "d" in suffix
    bool_flags = _bind_flags_from_suffix(suffix.replace("d", ""))
    if bool_flags is None:
        return None

    if has_description:
        parsed = _parse_bindd_args(bind_type, args)
        if parsed is None:
            return None
        bind, description = parsed
    else:
        parsed_bind = parse_bind_line(f"{bind_type} = {args}")
        if parsed_bind is None:
            return None
        bind = parsed_bind
        description = None

    # ``bindm`` is the mouse variant; combined forms like ``bindmd`` carry
    # the mouse semantics too, so check the whole suffix.
    is_mouse = "m" in bind.bind_type.removeprefix("bind")
    call = translate_dispatcher(bind.dispatcher.strip(), bind.arg, is_mouse=is_mouse)
    if call is None:
        return None

    flags: dict[str, Any] = dict(bool_flags)
    if description is not None:
        flags["description"] = description

    key_combo = quote_string(_format_key_combo(bind.mods, bind.key))
    if flags:
        return f"hl.bind({key_combo}, {call}, {format_table(flags, indent=0)})"
    return f"hl.bind({key_combo}, {call})"
