"""hyprland-config — Parse and edit Hyprland configuration files."""

import os
from pathlib import Path

from hyprland_config._bind import BindData, is_bind_keyword, parse_bind_line
from hyprland_config._expr import ExprError, evaluate_expression
from hyprland_config._migrate import (
    ConfigDeprecation,
    MigrationResult,
    check_deprecated,
    migrate,
)
from hyprland_config._model import (
    Assignment,
    BlankLine,
    Comment,
    Conditional,
    Document,
    ErrorLine,
    KeyValueLine,
    Keyword,
    Line,
    SectionClose,
    SectionOpen,
    Source,
    Variable,
)
from hyprland_config._parser import (
    ParseError,
    is_keyword,
    parse_file,
    parse_string,
)
from hyprland_config._source import SourceCycleError
from hyprland_config._types import Color, Gradient, Vec2
from hyprland_config._values import coerce_config_value, value_to_conf
from hyprland_config._writer import atomic_write


def parse_to_dict(
    path: str | Path,
    *,
    follow_sources: bool = True,
    lenient: bool = False,
) -> dict[str, str | list[str]]:
    """Parse a Hyprland config file into a flat dict.

    Variables are expanded, sources are followed by default.
    Keys use colon-separated paths (e.g. "general:gaps_in").
    Keys that appear once map to a string, keys that appear multiple
    times (e.g. bind, env, monitor) map to a list of strings.

    When *lenient* is True, unparseable lines are skipped instead of
    raising ``ParseError``.
    """
    doc = parse_file(Path(path).expanduser(), follow_sources=follow_sources, lenient=lenient)
    return doc.to_dict()


def _default_config() -> Path:
    """Resolve the default Hyprland config path at call time."""
    # Treat an empty XDG_CONFIG_HOME the same as unset — otherwise we'd build
    # a relative path against the current working directory.
    xdg = os.environ.get("XDG_CONFIG_HOME") or None
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "hypr" / "hyprland.conf"


def load(
    path: str | Path | None = None,
    *,
    follow_sources: bool = True,
    lenient: bool = False,
) -> Document:
    """Load a Hyprland config for reading and editing.

    With no arguments, loads ~/.config/hypr/hyprland.conf with source
    following enabled:

        config = load()
        config.set("general:gaps_in", 20)
        config.save()

    Source nodes get their .documents list populated with parsed
    sub-Documents, forming a navigable tree. Each sub-Document is
    independently serializable and saveable. Mutations default to
    recursive, and save() only writes files that were actually modified.

    When *lenient* is True, unparseable lines become ``ErrorLine`` nodes
    instead of raising ``ParseError``.  Access them via ``doc.errors``.
    """
    if path is None:
        path = _default_config()
        if not path.exists():
            raise FileNotFoundError(
                f"Hyprland config not found at {path}. Pass an explicit path to load()."
            )
    return parse_file(Path(path).expanduser(), follow_sources=follow_sources, lenient=lenient)


__all__ = [
    "Assignment",
    "BindData",
    "BlankLine",
    "Color",
    "Comment",
    "Conditional",
    "ConfigDeprecation",
    "Document",
    "ErrorLine",
    "ExprError",
    "Gradient",
    "Keyword",
    "KeyValueLine",
    "Line",
    "MigrationResult",
    "ParseError",
    "SectionClose",
    "SectionOpen",
    "Source",
    "SourceCycleError",
    "Variable",
    "Vec2",
    "atomic_write",
    "check_deprecated",
    "coerce_config_value",
    "evaluate_expression",
    "is_bind_keyword",
    "is_keyword",
    "load",
    "migrate",
    "parse_bind_line",
    "parse_to_dict",
    "parse_file",
    "parse_string",
    "value_to_conf",
]
