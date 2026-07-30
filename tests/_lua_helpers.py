"""Shared helpers for the Lua test files."""

import functools
import shutil
import subprocess

import pytest


@functools.cache
def _lua_available() -> bool:
    return any(
        shutil.which(name) is not None for name in ("lua", "lua5.5", "lua5.4", "lua5.3", "lua5.2")
    )


# The reader evaluates configs through the real interpreter, so tests that
# read Lua need `lua` itself — `requires_lua` below only covers `luac`.
requires_lua_interpreter = pytest.mark.skipif(
    not _lua_available(), reason="no lua interpreter on PATH"
)


@functools.cache
def _luac_path() -> str | None:
    """Locate a ``luac`` binary, preferring 5.4 then plain ``luac``."""
    for name in ("luac5.4", "luac"):
        path = shutil.which(name)
        if path is not None:
            return path
    return None


requires_lua = pytest.mark.skipif(
    _luac_path() is None,
    reason="no luac available — install lua to enable syntax validation",
)


def assert_lua_compiles(text: str) -> None:
    """Assert *text* parses cleanly through ``luac -p`` (parse-only mode).

    Skips when no ``luac`` is found so the test suite still runs on minimal
    environments; CI pins a Lua install so this is exercised there.
    """
    luac = _luac_path()
    if luac is None:
        pytest.skip("no luac available")
    result = subprocess.run(
        [luac, "-p", "-"],
        input=text,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or "(no stderr)"
        raise AssertionError(f"Emitted Lua failed to parse:\n{msg}\n---\n{text}")
