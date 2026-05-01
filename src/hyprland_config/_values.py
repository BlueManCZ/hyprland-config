"""Config value conversion — between Python types and Hyprland config strings."""


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
    """Convert a Python value to a Hyprland config string.

    Bools serialize as ``"true"`` / ``"false"`` (Hyprlang style). Other
    types are passed through ``str()``. This matches what
    :meth:`Document.set` writes into the file, so editors that read a
    value, transform it in Python, and write it back round-trip cleanly.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
