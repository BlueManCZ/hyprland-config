"""Keybind data model and parsing."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class BindData:
    """A single keybind definition."""

    bind_type: str = "bind"
    mods: list[str] = field(default_factory=list)
    key: str = ""
    dispatcher: str = ""
    arg: str = ""
    owned: bool = True

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
        """Serialize to a config line."""
        line = f"{self.bind_type} = {self.mods_str}, {self.key}, {self.dispatcher}"
        if self.arg:
            line += f", {self.arg}"
        else:
            line += ","
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
    """Parse a ``'bind = MODS, KEY, dispatcher, arg'`` line."""
    if "=" not in line:
        return None
    btype, _, rest = line.partition("=")
    btype = btype.strip()
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
        owned=True,
    )
