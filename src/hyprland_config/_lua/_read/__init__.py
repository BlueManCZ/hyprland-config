"""Read a Hyprland Lua config into a :class:`Document`.

Pairs with the ``serialize_lua`` emitter — together they give consumers
the same Document-AST view of a Hyprland config regardless of whether
the on-disk format is Hyprlang or Lua.

Implementation strategy
-----------------------

We don't hand-roll a Lua parser. The wiki encourages users to write
configs with locals, loops (``for i = 1, 10 do hl.bind(...)`` is in the
example config), string concatenation, and ``dofile`` chains, and a
subset parser would inevitably misread something. Instead we let *real*
Lua interpret the file, with a wrapper script (``_wrapper.lua``) that:

- Replaces ``hl`` and ``hl.dsp.*`` with stubs that record their call
  arguments rather than mutating compositor state.
- Replaces ``dofile`` so nested sub-files are recorded with their
  correct origin path.
- Serialises the recorded calls as one JSON object per line, into a
  file the Python side names (stdout stays the user config's to print
  to).

The Python side drives the wrapper through ``subprocess``, parses the
records, and synthesises ``Assignment`` and ``Keyword`` nodes that
mirror what ``parse_string`` produces for the equivalent Hyprlang.
Consumers see a single AST shape regardless of input language.

Module layout:

- :mod:`._runner` — subprocess driving and the public :func:`load_lua` entry.
- :mod:`._records` — record walker and dispatch table.
- :mod:`._config` — ``hl.config`` table flattening and scalar/list/gradient
  rendering.
- :mod:`._keywords` — per-keyword shape converters (monitor, bezier, …).
- :mod:`._bind` — bind / unbind reverse-mapping.
- :mod:`._dispatchers` — Lua ``hl.dsp.*`` → Hyprlang dispatcher mapping.
"""

from hyprland_config._lua._read._runner import LuaReaderError, load_lua

__all__ = ["LuaReaderError", "load_lua"]
