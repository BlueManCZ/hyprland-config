"""Keybind data model and parsing."""

import re
from dataclasses import dataclass, field

# Hyprland generates bind variants combinatorially from flag chars
# (e, l, r, n, m, t, i, s, d, p). A regex covers all current and future
# combinations without needing manual enumeration.
_BIND_RE = re.compile(r"^bind[elnrmtisdp]*$")


def is_bind_keyword(name: str) -> bool:
    """Return True if *name* is a bind-variant keyword (bind, binde, bindm …)."""
    return _BIND_RE.match(name) is not None


@dataclass(slots=True)
class BindData:
    """A single keybind definition."""

    bind_type: str = "bind"
    mods: list[str] = field(default_factory=list)
    key: str = ""
    dispatcher: str = ""
    arg: str = ""

    @property
    def combo(self) -> tuple[tuple[str, ...], str]:
        """Normalized (mods_tuple, key) for comparison and deduplication."""
        return (
            tuple(sorted(m.upper() for m in self.mods)),
            self.key.upper(),
        )

    @property
    def mods_str(self) -> str:
        """Space-joined modifier string."""
        return " ".join(self.mods)

    def to_line(self) -> str:
        """Serialize to a config line.

        ``bindm`` is strict about argument count and rejects a trailing comma
        with ``bind: too many args``, so the trailing comma is omitted when
        ``arg`` is empty. Other bind variants tolerate either form.
        """
        line = f"{self.bind_type} = {self.mods_str}, {self.key}, {self.dispatcher}"
        if self.arg:
            line += f", {self.arg}"
        return line

    def format_shortcut(self) -> str:
        """Format key combination for display: ``'SUPER + SHIFT + A'``."""
        parts = [m.upper() for m in self.mods]
        if self.key:
            parts.append(self.key.upper() if len(self.key) == 1 else self.key)
        return " + ".join(parts) if parts else "(none)"

    def format_action(self) -> str:
        """Action string: ``'exec: firefox'`` or ``'killactive'``."""
        if self.arg:
            return f"{self.dispatcher}: {self.arg}"
        return self.dispatcher


def parse_bind_line(line: str) -> BindData | None:
    """Parse a ``'bind = MODS, KEY, dispatcher, arg'`` line.

    Returns ``None`` if the line's keyword is not a bind variant
    (``bind``, ``binde``, ``bindm``, …) or if it has fewer than the
    three required comma-separated parts after ``=``.
    """
    if "=" not in line:
        return None
    btype, _, rest = line.partition("=")
    btype = btype.strip()
    if not is_bind_keyword(btype):
        return None
    parts = [p.strip() for p in rest.split(",", 3)]
    if len(parts) < 3:
        return None
    mods_str = parts[0]
    key = parts[1]
    dispatcher = parts[2]
    arg = parts[3] if len(parts) > 3 else ""
    mods = mods_str.split() if mods_str else []
    return BindData(
        bind_type=btype,
        mods=mods,
        key=key,
        dispatcher=dispatcher,
        arg=arg,
    )
