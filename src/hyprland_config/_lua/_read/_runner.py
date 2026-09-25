"""Public entry: load a Hyprland Lua config file into a :class:`Document`.

Drives the Lua wrapper script (``_wrapper.lua``) via subprocess, parses
the JSON records it writes, and feeds them to
:func:`._records.records_to_document`.

The only runtime requirement is a ``lua`` binary on ``PATH``. Any
machine running Hyprland 0.55+ with a Lua config has one — if it
didn't, Hyprland itself couldn't load the config. :func:`load_lua`
raises :class:`LuaReaderError` with a clear message when ``lua`` is
missing so calling code can surface that to the user.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hyprland_config._core._model import Document
from hyprland_config._hyprlang._parser import ParseError
from hyprland_config._lua._read._records import records_to_document

# Names we'll probe for the Lua interpreter, in preference order. Plain
# ``lua`` first (most distros symlink it); then versioned binaries newest
# first so a system shipping both 5.4 and 5.3 picks 5.4.
_LUA_BINARY_CANDIDATES = ("lua", "lua5.5", "lua5.4", "lua5.3", "lua5.2")


def _find_lua() -> str | None:
    """Locate a usable Lua interpreter on ``PATH`` (or via ``$HYPRLAND_CONFIG_LUA``)."""
    override = os.environ.get("HYPRLAND_CONFIG_LUA")
    if override:
        return override
    for name in _LUA_BINARY_CANDIDATES:
        found = shutil.which(name)
        if found is not None:
            return found
    return None


# The wrapper script lives next to this module — keep it as a sibling
# .lua file rather than an embedded string so a Lua-aware editor (or
# ``luac -p``) can verify it independently.
_WRAPPER_SCRIPT = Path(__file__).parent / "_wrapper.lua"

# How long we'll wait for the user's config to finish. A pathological
# ``for`` loop or busy callback would otherwise hang the reader; 10s is
# generous for any realistic config (Hyprland's own timeouts are far
# tighter).
_LUA_TIMEOUT_SECONDS = 10


class LuaReaderError(ParseError):
    """Raised when the Lua reader can't produce a Document.

    Subclasses :class:`ParseError` so callers can catch both Hyprlang and
    Lua read failures with one ``except``. Covers three broad cases:
    ``lua`` is missing from ``PATH``, the user's Lua file failed to
    load/execute, and unparseable wrapper output.
    """


def load_lua(path: str | Path) -> Document:
    """Parse a Hyprland Lua config file and return a :class:`Document`.

    Walks ``dofile("…")`` chains transparently and builds the same
    tree-shaped Document the Hyprlang parser produces: each sub-file
    becomes a nested :class:`Document` wrapped in a :class:`Source`
    node on its parent. Consumers can iterate the result with the
    same ``recursive`` / ``exclude_sources`` semantics regardless of
    whether the on-disk format is Hyprlang or Lua.

    Comments, blank lines, and the user's local variable assignments
    aren't preserved — only the *effects* of running the config (i.e.
    everything ``hl.*`` was called with) appear in the Document.
    """
    entry = Path(path).expanduser()
    return records_to_document(_run_wrapper(entry), entry_path=entry)


def _run_wrapper(path: Path) -> list[dict[str, Any]]:
    """Invoke the Lua wrapper and parse the records it writes."""
    lua = _find_lua()
    if lua is None:
        raise LuaReaderError(
            "the `lua` interpreter is required to read Lua-mode Hyprland "
            "configs; install it via your distro's package manager "
            "(usually `lua` or `lua5.4`) and try again."
        )

    # The wrapper writes records to a file of our choosing and we throw its
    # stdout away: the user's config owns stdout, and anything it prints
    # there (directly, or from a command it starts) used to be read back as
    # a record and fail the JSON parse.
    with tempfile.TemporaryDirectory(prefix="hyprland-config-") as tmpdir:
        records_path = Path(tmpdir) / "records.jsonl"
        try:
            result = subprocess.run(
                [lua, str(_WRAPPER_SCRIPT), str(path), str(records_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=_LUA_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise LuaReaderError(
                f"reading {path} timed out after {_LUA_TIMEOUT_SECONDS}s — "
                "check for infinite loops in the config."
            ) from exc

        if result.returncode != 0:
            raise LuaReaderError(
                f"lua failed to load {path}: {result.stderr.strip() or 'unknown error'}"
            )

        try:
            output = records_path.read_text()
        except OSError as exc:
            raise LuaReaderError(
                f"reading {path} produced no records: the config ended the process "
                "before they could be written (an `os.exit()` in the config does this)."
            ) from exc

    records: list[dict[str, Any]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise LuaReaderError(
                f"wrapper produced unparseable output line: {line!r} ({exc})"
            ) from exc
    return records
