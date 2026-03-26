"""Config value conversion — between Python types and Hyprland config strings."""

import re

# Matches bare hex color tokens like "ff1a2b3c" (6 or 8 hex digits, no 0x prefix).
_GRADIENT_HEX_RE = re.compile(r"^[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")


def coerce_config_value(value_str: str, type_name: str) -> bool | int | float | str:
    """Convert a config file string to the appropriate Python type.

    *type_name* is one of ``"bool"``, ``"int"``, ``"float"``, or any
    string type (``"string"``, ``"color"``, etc.).  Unknown types are
    returned as-is.
    """
    try:
        if type_name == "bool":
            return value_str.lower() in ("true", "1", "yes")
        elif type_name in ("int", "choice"):
            return int(value_str)
        elif type_name == "float":
            return float(value_str)
    except ValueError:
        pass
    return value_str


def value_to_conf(value: bool | int | float | str) -> str:
    """Convert a Python value to Hyprland config format.

    Bools become ``"0"`` / ``"1"`` (IPC-style), not ``"true"`` / ``"false"``
    (Hyprlang-style).  Both forms are accepted by Hyprland, and ``"0"`` / ``"1"``
    is used here because HyprMod's managed config is applied via IPC reload.
    Gradient hex tokens are normalized to include the ``0x`` prefix required
    by config files (IPC returns bare hex like ``"ff1a2b3c"``).
    """
    if isinstance(value, bool):
        return str(int(value))
    s = str(value)
    # Normalize gradient hex tokens: IPC returns colors without 0x prefix
    # (e.g. "ff1a2b3c ff4d5e6f 45deg"), but config files need 0x prefixes.
    if "deg" in s and not s.startswith("0x"):
        parts = s.split()
        normalized = []
        for p in parts:
            if not p.endswith("deg") and _GRADIENT_HEX_RE.match(p):
                p = f"0x{p}"
            normalized.append(p)
        return " ".join(normalized)
    return s
