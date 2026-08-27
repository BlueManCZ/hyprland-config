"""Keybind data model — shared between Hyprlang and Lua bridges."""

from dataclasses import dataclass, field

# Bind keyword suffix char → Lua flag-table field name. ``d`` is handled
# separately (it adds a string ``description`` field and shifts the
# positional layout, rather than just toggling a bool), and ``s`` / ``p``
# have no documented Lua equivalent yet. The forward and reverse Lua
# bridges both consume this single source of truth.
BIND_FLAG_MAP: dict[str, str] = {
    "e": "repeating",
    "l": "locked",
    "m": "mouse",
    "r": "release",
    "n": "non_consuming",
    "t": "transparent",
    "i": "ignore_mods",
}


def has_description_flag(bind_type: str) -> bool:
    """Return whether a bind keyword carries the ``d`` description flag."""
    return bind_type.startswith("bind") and "d" in bind_type[4:]


@dataclass(slots=True)
class BindData:
    """A single keybind definition."""

    bind_type: str = "bind"
    mods: list[str] = field(default_factory=list)
    key: str = ""
    dispatcher: str = ""
    arg: str = ""
    description: str = ""

    @property
    def combo(self) -> tuple[tuple[str, ...], str]:
        """Normalized (mods_tuple, key) for comparison and deduplication."""
        return (
            tuple(sorted(m.upper() for m in self.mods)),
            self.key.upper(),
        )

    @property
    def mods_str(self) -> str:
        return " ".join(self.mods)

    def to_line(self) -> str:
        """Serialize to a config line.

        ``bindm`` is strict about argument count and rejects a trailing comma
        with ``bind: too many args``, so the trailing comma is omitted when
        ``arg`` is empty. Other bind variants tolerate either form.
        """
        parts = [f"{self.bind_type} = {self.mods_str}", self.key]
        if has_description_flag(self.bind_type):
            parts.append(self.description)
        parts.append(self.dispatcher)
        if self.arg:
            parts.append(self.arg)
        return ", ".join(parts)

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
