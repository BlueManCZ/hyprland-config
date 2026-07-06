"""hyprland-config — Parse and edit Hyprland configuration files."""

import os
from pathlib import Path

from hyprland_config._converter import (
    ConversionPlan,
    ConversionResult,
    UnmappedLine,
    analyze_conversion,
    execute_conversion,
)
from hyprland_config._core import (
    ANIM_CHILDREN,
    ANIM_FLAT,
    ANIM_LOOKUP,
    ANIMATION_TREE,
    HYPRLAND_NATIVE_CURVES,
    LAYER_BOOL_EFFECTS,
    LAYERRULE_V3_VERSION,
    V3_BOOL_EFFECTS,
    V3_BOOL_MATCHERS,
    WINDOWRULE_V3_VERSION,
    AnimationData,
    Assignment,
    BezierData,
    BindData,
    BlankLine,
    Color,
    Comment,
    Document,
    Keyword,
    Rule,
    Source,
    atomic_write,
    coerce_config_value,
    get_styles_for,
    normalize_gradient_string,
    parse_hyprlang_bool,
    parse_version,
    split_top_level,
    value_to_conf,
)
from hyprland_config._hyprlang import (
    ParseError,
    SourceCycleError,
    is_bind_keyword,
    parse_bind_line,
    parse_file,
    parse_string,
    render_rule_hyprlang,
    render_rule_live,
    serialize_hyprlang,
)
from hyprland_config._lua import (
    LuaFile,
    LuaReaderError,
    define_submap_to_lua,
    dispatch_to_lua,
    keyword_to_lua,
    load_lua,
    render_rule_lua,
    serialize_lua,
    serialize_lua_tree,
)
from hyprland_config._migrate import (
    ConfigDeprecation,
    MigrationResult,
    check_deprecated,
    migrate,
    normalize_rules,
)


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


def default_config_dir() -> Path:
    """Return ``$XDG_CONFIG_HOME/hypr`` (or ``~/.config/hypr`` if unset)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "hypr"


def default_hyprlang_entrypoint() -> Path:
    """Path of the canonical Hyprlang entrypoint (``hyprland.conf``)."""
    return default_config_dir() / "hyprland.conf"


def default_lua_entrypoint() -> Path:
    """Path of the Hyprland 0.55+ Lua entrypoint (``hyprland.lua``)."""
    return default_config_dir() / "hyprland.lua"


def default_entrypoint() -> Path:
    """Return whichever entrypoint Hyprland would load.

    Hyprland 0.55+ prefers ``hyprland.lua`` when present, falling back
    to ``hyprland.conf``. Pre-0.55 only ever reads ``hyprland.conf``.
    Returns the Hyprlang path when neither exists yet.
    """
    lua = default_lua_entrypoint()
    return lua if lua.exists() else default_hyprlang_entrypoint()


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
        path = default_hyprlang_entrypoint()
        if not path.exists():
            raise FileNotFoundError(
                f"Hyprland config not found at {path}. Pass an explicit path to load()."
            )
    return parse_file(Path(path).expanduser(), follow_sources=follow_sources, lenient=lenient)


def load_any(
    path: str | Path,
    *,
    follow_sources: bool = True,
    lenient: bool = False,
) -> Document:
    """Load a Hyprland config, picking Hyprlang or Lua based on the suffix.

    Convenience for callers that don't know in advance which format the
    user has on disk. ``.lua`` paths go through :func:`load_lua`, anything
    else through :func:`load`. ``follow_sources`` and ``lenient`` are
    forwarded to the Hyprlang loader (the Lua reader walks ``dofile``
    chains unconditionally and ignores both).
    """
    target = Path(path).expanduser()
    if target.suffix == ".lua":
        return load_lua(target)
    return load(target, follow_sources=follow_sources, lenient=lenient)


def serialize_any(doc: Document, path: str | Path) -> str:
    """Render *doc* in the format implied by *path*'s suffix.

    Symmetric counterpart to :func:`load_any` — ``.lua`` paths route
    through :func:`serialize_lua`, anything else through
    :func:`serialize_hyprlang`. The path is inspected only for its
    suffix; no I/O is performed.
    """
    if Path(path).suffix == ".lua":
        return serialize_lua(doc)
    return serialize_hyprlang(doc)


__all__ = [
    "ANIM_CHILDREN",
    "ANIM_FLAT",
    "ANIM_LOOKUP",
    "ANIMATION_TREE",
    "AnimationData",
    "Assignment",
    "BezierData",
    "BindData",
    "BlankLine",
    "Color",
    "Comment",
    "ConfigDeprecation",
    "ConversionPlan",
    "ConversionResult",
    "Document",
    "HYPRLAND_NATIVE_CURVES",
    "Keyword",
    "LAYER_BOOL_EFFECTS",
    "LAYERRULE_V3_VERSION",
    "LuaFile",
    "LuaReaderError",
    "MigrationResult",
    "ParseError",
    "Rule",
    "Source",
    "SourceCycleError",
    "UnmappedLine",
    "V3_BOOL_EFFECTS",
    "V3_BOOL_MATCHERS",
    "WINDOWRULE_V3_VERSION",
    "analyze_conversion",
    "atomic_write",
    "check_deprecated",
    "coerce_config_value",
    "default_config_dir",
    "default_entrypoint",
    "default_hyprlang_entrypoint",
    "default_lua_entrypoint",
    "define_submap_to_lua",
    "dispatch_to_lua",
    "execute_conversion",
    "get_styles_for",
    "is_bind_keyword",
    "keyword_to_lua",
    "load",
    "load_any",
    "load_lua",
    "migrate",
    "normalize_gradient_string",
    "normalize_rules",
    "parse_bind_line",
    "parse_hyprlang_bool",
    "parse_string",
    "parse_to_dict",
    "parse_version",
    "render_rule_hyprlang",
    "render_rule_live",
    "render_rule_lua",
    "serialize_any",
    "serialize_hyprlang",
    "serialize_lua",
    "serialize_lua_tree",
    "split_top_level",
    "value_to_conf",
]
