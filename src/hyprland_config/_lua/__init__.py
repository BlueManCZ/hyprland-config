"""Hyprland Lua bridge — bidirectional ``Document`` ↔ ``.lua`` translation.

Subpackages mirror the two directions:

- :mod:`._emit` — :class:`~hyprland_config._core._model.Document` → ``.lua`` text.
- :mod:`._read` — ``.lua`` file → :class:`~hyprland_config._core._model.Document`,
  driven through the bundled ``_wrapper.lua`` script and a real Lua interpreter.

Both halves consume the same :class:`Document` AST that the
:mod:`hyprland_config._hyprlang` package produces and parses, so the
on-disk format is the only thing that changes between formats.
"""

from hyprland_config._lua._emit import (
    LuaFile,
    define_submap_to_lua,
    dispatch_to_lua,
    emit_keyword_line,
    emit_option_assignment,
    keyword_to_lua,
    render_rule_lua,
    serialize_lua,
    serialize_lua_file,
    serialize_lua_tree,
)
from hyprland_config._lua._read import LuaReaderError, load_lua

__all__ = [
    "LuaFile",
    "LuaReaderError",
    "define_submap_to_lua",
    "dispatch_to_lua",
    "emit_keyword_line",
    "emit_option_assignment",
    "keyword_to_lua",
    "load_lua",
    "render_rule_lua",
    "serialize_lua",
    "serialize_lua_file",
    "serialize_lua_tree",
]
