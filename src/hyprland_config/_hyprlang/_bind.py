"""Hyprlang bind-line text parsing — recognise and decompose ``bind = …`` lines."""

from hyprland_config._core._bind import BindData, has_description_flag

# Hyprland accepts ``bind`` plus any unique subset of these suffix chars
# (e/l/n/r/m/t/i/s/d/p). Each flag may appear at most once and order doesn't
# matter; we accept the bare keyword too.
_BIND_FLAGS = frozenset("elnrmtisdp")


def is_bind_keyword(name: str) -> bool:
    """Return True if *name* is a bind-variant keyword (bind, binde, bindm …)."""
    if not name.startswith("bind"):
        return False
    suffix = name[4:]
    return len(set(suffix)) == len(suffix) and set(suffix) <= _BIND_FLAGS


def parse_bind_line(line: str) -> BindData | None:
    """Parse a Hyprland keybind line.

    Regular binds use ``MODS, KEY, DISPATCHER [, ARG]``. Bind variants
    containing the ``d`` flag insert a description before the dispatcher:
    ``MODS, KEY, DESCRIPTION, DISPATCHER [, ARG]``.

    Returns ``None`` if the line's keyword is not a bind variant
    (``bind``, ``binde``, ``bindm``, …) or if it has too few
    comma-separated fields for that variant.
    """
    if "=" not in line:
        return None
    btype, _, rest = line.partition("=")
    btype = btype.strip()
    if not is_bind_keyword(btype):
        return None
    has_description = has_description_flag(btype)
    parts = [p.strip() for p in rest.split(",", 4 if has_description else 3)]
    minimum_parts = 4 if has_description else 3
    if len(parts) < minimum_parts:
        return None
    mods_str = parts[0]
    key = parts[1]
    if has_description:
        description = parts[2]
        dispatcher = parts[3]
        arg_index = 4
    else:
        description = ""
        dispatcher = parts[2]
        arg_index = 3
    # A trailing comma in the bind line (``MODS, KEY, killactive,``) carries
    # no meaning — it represents an empty fifth field that got absorbed into
    # the arg slot when we split with ``maxsplit=3``. Strip it so dispatchers
    # don't receive ``"togglesplit,"`` as their arg.
    arg = parts[arg_index].rstrip(",").strip() if len(parts) > arg_index else ""
    mods = mods_str.split() if mods_str else []
    return BindData(
        bind_type=btype,
        mods=mods,
        key=key,
        dispatcher=dispatcher,
        arg=arg,
        description=description,
    )
