"""Lua reader tolerance for Hyprland 0.57 config APIs.

0.57 configs query live state at load time (``hl.get_devices()`` and
friends) and register runtime callbacks. Neither should abort or cause
side effects during a read-only parse, and partial failures should be
visible to the caller.
"""

from pathlib import Path

from hyprland_config import Assignment, Keyword, load_lua
from tests._lua_helpers import requires_lua_interpreter

pytestmark = requires_lua_interpreter


def _assignments(doc) -> dict[str, str]:
    return {ln.full_key: ln.value for _doc, ln in doc.iter_lines() if isinstance(ln, Assignment)}


def _keywords(doc, key: str) -> list[str]:
    return [ln.value for _doc, ln in doc.iter_lines() if isinstance(ln, Keyword) and ln.key == key]


class TestQueryApis:
    def test_devices_and_monitors_loops_do_not_abort(self, tmp_path: Path) -> None:
        path = tmp_path / "config.lua"
        path.write_text(
            "hl.config({ general = { gaps_in = 5 } })\n"
            "for _, dev in ipairs(hl.get_devices()) do\n"
            "    hl.device({ name = dev.name, enabled = true })\n"
            "end\n"
            "for _, mon in ipairs(hl.get_monitors()) do\n"
            "    hl.monitor({ output = mon.name })\n"
            "end\n"
            "for _, ws in ipairs(hl.get_workspaces()) do\n"
            "    hl.workspace_rule({ workspace = ws.name })\n"
            "end\n"
            "for _, win in ipairs(hl.get_windows()) do\n"
            "    hl.window_rule({ match = { class = win.class } })\n"
            "end\n"
            "hl.reload_config()\n"
        )
        doc = load_lua(path)
        assert _assignments(doc) == {"general:gaps_in": "5"}
        assert doc.read_warnings == []


class TestRuntimeCallbacks:
    def test_runtime_events_are_not_executed(self, tmp_path: Path) -> None:
        marker = tmp_path / "callback-ran"
        path = tmp_path / "config.lua"
        path.write_text(
            "local function touch()\n"
            f'    local f = io.open("{marker}", "w")\n'
            "    if f then f:write('ran') f:close() end\n"
            "end\n"
            'hl.on("config.unload", touch)\n'
            'hl.on("window.minimize", touch)\n'
            'hl.on("window.update_state", touch)\n'
        )
        load_lua(path)
        assert not marker.exists()

    def test_startup_execs_still_recorded(self, tmp_path: Path) -> None:
        path = tmp_path / "config.lua"
        path.write_text('hl.on("hyprland.start", function() hl.exec_cmd("waybar") end)\n')
        assert _keywords(load_lua(path), "exec-once") == ["waybar"]


class TestPartialReadWarnings:
    def test_errors_are_reported_and_document_survives(self, tmp_path: Path) -> None:
        path = tmp_path / "config.lua"
        path.write_text('hl.config({ general = { gaps_in = 5 } })\nerror("boom")\n')
        doc = load_lua(path)
        assert _assignments(doc) == {"general:gaps_in": "5"}
        assert any("boom" in warning for warning in doc.read_warnings)

    def test_clean_config_has_no_warnings(self, tmp_path: Path) -> None:
        path = tmp_path / "config.lua"
        path.write_text("hl.config({ general = { gaps_in = 5 } })\n")
        assert load_lua(path).read_warnings == []
