"""Config value conversion — between Python types and Hyprland config strings."""

import re

import hyprland_schema

# Hyprland's Hyprlang parser accepts these (case-insensitive) for boolean
# fields. Single source of truth for the whole library — every code path
# that needs to coerce a string to a bool should route through
# :func:`parse_hyprlang_bool`.
HYPRLANG_TRUE_WORDS: frozenset[str] = frozenset({"true", "yes", "on", "1"})
HYPRLANG_FALSE_WORDS: frozenset[str] = frozenset({"false", "no", "off", "0"})

# Recognise a bare integer / float literal in a Hyprlang value string. Shared
# by the Lua value coercer and the conditional-expression translator so both
# agree on what counts as a number.
INT_LITERAL_RE = re.compile(r"^-?\d+$")
FLOAT_LITERAL_RE = re.compile(r"^-?\d+\.\d+$")


def option_type(full_key: str) -> str | None:
    """Return the type Hyprland gives the option *full_key*.

    ``None`` for a key the schema doesn't carry: a plugin's option, a typo,
    or one newer than the installed hyprland-schema. Callers that need a
    type fall back to reading the value's shape.

    Resolved against the bundled schema, i.e. the newest Hyprland the
    installed hyprland-schema knows. Option types do change between
    releases — ``general:gaps_in`` was a string before 0.55 — so a consumer
    targeting an older compositor wants its hyprland-schema pinned to match.

    A ``device { … }`` block's fields override the matching ``input:``
    option, so ``device:kb_layout`` resolves as ``input:kb_layout``.
    """
    if full_key.startswith("device:"):
        full_key = f"input:{full_key.removeprefix('device:')}"
    opt = hyprland_schema.OPTIONS_BY_KEY.get(full_key)
    return opt.type if opt is not None else None


def parse_hyprlang_bool(value: object) -> bool | None:
    """Best-effort coerce *value* into a Hyprlang-recognised boolean.

    Returns ``None`` when *value* doesn't look like a boolean — callers
    decide whether to fall through, raise, or default. Accepts:

    - Native ``bool`` (passthrough).
    - ``int`` (``0`` → False, anything else → True).
    - ``str`` in ``HYPRLANG_TRUE_WORDS`` / ``HYPRLANG_FALSE_WORDS``
      (case-insensitive, whitespace-trimmed).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        token = value.strip().lower()
        if token in HYPRLANG_TRUE_WORDS:
            return True
        if token in HYPRLANG_FALSE_WORDS:
            return False
    return None


def coerce_config_value(value_str: str, type_name: str) -> bool | int | float | str:
    """Convert a config file string to the appropriate Python type.

    *type_name* is one of ``"bool"``, ``"int"``, ``"float"``, or any
    string type (``"string"``, ``"color"``, etc.).  Unknown types are
    returned as-is.
    """
    try:
        if type_name == "bool":
            parsed = parse_hyprlang_bool(value_str)
            return parsed if parsed is not None else False
        elif type_name in ("int", "choice"):
            return int(value_str)
        elif type_name == "float":
            return float(value_str)
    except ValueError:
        pass
    return value_str


def value_to_conf(value: bool | int | float | str) -> str:
    """Convert a Python value to a Hyprland config string.

    Bools serialize as ``"true"`` / ``"false"`` (Hyprlang style). Other
    types are passed through ``str()``. This matches what
    :meth:`Document.set` writes into the file, so editors that read a
    value, transform it in Python, and write it back round-trip cleanly.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
