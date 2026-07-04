"""Tests for the Lua reader (the inverse of ``serialize_lua``).

These spawn the system ``lua`` interpreter to evaluate the test
configs, so the suite is skipped on environments that don't ship one.
On Hyprland 0.55+ machines (the target users for this reader) ``lua``
is always present.
"""

import functools
import shutil
from pathlib import Path

import pytest

from hyprland_config import (
    Assignment,
    Keyword,
    LuaReaderError,
    load_lua,
    parse_string,
    serialize_lua,
)
from hyprland_config._lua import serialize_lua_tree


@functools.cache
def _lua_available() -> bool:
    return any(
        shutil.which(name) is not None for name in ("lua", "lua5.5", "lua5.4", "lua5.3", "lua5.2")
    )


requires_lua = pytest.mark.skipif(not _lua_available(), reason="no lua interpreter on PATH")

pytestmark = requires_lua


def _write_lua(tmp_path: Path, code: str) -> Path:
    path = tmp_path / "config.lua"
    path.write_text(code)
    return path


def _assignments(doc) -> dict[str, str]:
    # Walk the whole tree — Lua docs nest sub-files under :class:`Source`
    # nodes (mirroring how the Hyprlang parser handles ``source = …``),
    # so iterating ``doc.lines`` alone misses anything reached via dofile.
    return {ln.full_key: ln.value for _doc, ln in doc.iter_lines() if isinstance(ln, Assignment)}


def _keywords(doc, key: str) -> list[str]:
    return [ln.value for _doc, ln in doc.iter_lines() if isinstance(ln, Keyword) and ln.key == key]


def _rules(doc, kind: str):
    from hyprland_config import Rule

    return [ln for _doc, ln in doc.iter_lines() if isinstance(ln, Rule) and ln.kind == kind]


class TestConfigOptions:
    def test_top_level_option(self, tmp_path: Path) -> None:
        path = _write_lua(tmp_path, "hl.config({ general = { gaps_in = 5 } })\n")
        doc = load_lua(path)
        assert _assignments(doc) == {"general:gaps_in": "5"}

    def test_nested_subsection(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            "hl.config({ decoration = { blur = { enabled = true, size = 3 } } })\n",
        )
        doc = load_lua(path)
        assert _assignments(doc) == {
            "decoration:blur:enabled": "true",
            "decoration:blur:size": "3",
        }

    def test_col_subnamespace_uses_dotted_leaf(self, tmp_path: Path) -> None:
        # Hyprlang spells these keys ``general:col.X``, not ``general:col:X``.
        # The emitter flattens them through a ``col`` Lua sub-table; the
        # reader has to recognise the convention and reconstruct the dotted form.
        path = _write_lua(
            tmp_path,
            "hl.config({ general = { col = { inactive_border = 'rgba(595959aa)' } } })\n",
        )
        doc = load_lua(path)
        assert "general:col.inactive_border" in _assignments(doc)

    def test_gradient_table_renders_as_hyprlang_string(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            """hl.config({
                general = {
                    col = {
                        active_border = {
                            colors = {'rgba(b4e718ee)', 'rgba(00ff99ee)'},
                            angle = 45,
                        },
                    },
                },
            })""",
        )
        doc = load_lua(path)
        assert (
            _assignments(doc)["general:col.active_border"] == "rgba(b4e718ee) rgba(00ff99ee) 45deg"
        )

    def test_bool_values_serialise_as_true_false(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            "hl.config({ misc = { vrr = true, vfr = false } })\n",
        )
        doc = load_lua(path)
        out = _assignments(doc)
        assert out["misc:vrr"] == "true"
        assert out["misc:vfr"] == "false"

    def test_integer_floats_collapse(self, tmp_path: Path) -> None:
        # 1.0 should come back as "1" not "1.0" — Hyprlang's parser
        # accepts both for cssgap/int but our existing parsed form is int.
        path = _write_lua(tmp_path, "hl.config({ decoration = { active_opacity = 1.0 } })\n")
        assert _assignments(load_lua(path))["decoration:active_opacity"] == "1"


class TestKeywordCalls:
    def test_env(self, tmp_path: Path) -> None:
        path = _write_lua(tmp_path, "hl.env('XCURSOR_SIZE', '24')\n")
        assert _keywords(load_lua(path), "env") == ["XCURSOR_SIZE, 24"]

    def test_monitor(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            """hl.monitor({
                output = 'DP-1',
                mode = '2560x1440@144',
                position = '0x0',
                scale = 1,
                bitdepth = 10,
            })""",
        )
        # Field order in the rendered CSV: output, mode, position, scale, then
        # remaining keys sorted alphabetically.
        assert _keywords(load_lua(path), "monitor") == ["DP-1, 2560x1440@144, 0x0, 1, bitdepth, 10"]

    def test_monitor_disabled_round_trips_to_short_form(self, tmp_path: Path) -> None:
        # ``disabled = true`` in Lua maps back to Hyprlang's
        # ``monitor = OUTPUT, disable`` short-form so line-oriented consumers
        # (hyprmod's monitor page) see the canonical legacy shape.
        path = _write_lua(tmp_path, "hl.monitor({ output = 'DP-1', disabled = true })")
        assert _keywords(load_lua(path), "monitor") == ["DP-1, disable"]

    def test_monitor_explicit_enable_reads_as_full_line(self, tmp_path: Path) -> None:
        # ``disabled = false`` is the emitter's explicit re-enable marker; the
        # reader must drop it rather than leak a spurious ``disabled, false``
        # extra into the Hyprlang line.
        path = _write_lua(
            tmp_path,
            "hl.monitor({ output = 'DP-1', mode = '2560x1440@144', "
            "position = '0x0', scale = 1, disabled = false })",
        )
        assert _keywords(load_lua(path), "monitor") == ["DP-1, 2560x1440@144, 0x0, 1"]

    def test_bezier(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            "hl.curve('myCurve', { type = 'bezier', points = {{0.05,0.9},{0.1,1.05}} })",
        )
        assert _keywords(load_lua(path), "bezier") == ["myCurve, 0.05, 0.9, 0.1, 1.05"]

    def test_animation(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            "hl.animation({ leaf='windows', enabled=true, speed=7,"
            " bezier='easeOut', style='slide' })",
        )
        # Canonical Hyprlang booleans are ``true``/``false`` (project-wide
        # convention since v0.4.5) — not the legacy ``1``/``0``.
        assert _keywords(load_lua(path), "animation") == ["windows, true, 7, easeOut, slide"]

    def test_workspace_rule(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            "hl.workspace_rule({ workspace = 1, monitor = 'DP-1', default = true })",
        )
        assert _keywords(load_lua(path), "workspace") == ["1, default:true, monitor:DP-1"]

    def test_gesture(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            "hl.gesture({ fingers = 3, direction = 'horizontal', action = 'workspace' })",
        )
        assert _keywords(load_lua(path), "gesture") == ["3, horizontal, workspace"]

    def test_permission(self, tmp_path: Path) -> None:
        path = _write_lua(tmp_path, "hl.permission('/usr/bin/grim', 'screencopy', 'allow')")
        assert _keywords(load_lua(path), "permission") == ["/usr/bin/grim, screencopy, allow"]

    def test_unbind_reverts_to_comma_form(self, tmp_path: Path) -> None:
        # hyprmod's OverrideTracker splits the unbind value on the first
        # comma to pull ``(mods, key)`` apart. A raw passthrough of the
        # ``"SUPER + Q"`` combo string from the Lua call would defeat that,
        # so the reader has to undo the Lua-side join.
        path = _write_lua(
            tmp_path,
            "hl.unbind('SUPER + Q')\nhl.unbind('F1')\nhl.unbind('SUPER + SHIFT + mouse:272')\n",
        )
        assert _keywords(load_lua(path), "unbind") == [
            "SUPER, Q",
            ", F1",
            "SUPER SHIFT, mouse:272",
        ]

    def test_plugin_load_reverts_to_plugin_keyword(self, tmp_path: Path) -> None:
        # ``hl.plugin`` is a namespace table on the real runtime, not a
        # function — the wrapper has to mirror that shape so user calls
        # land in our recorder instead of crashing on the catch-all
        # ``__index`` (which returns a no-op function).
        path = _write_lua(
            tmp_path,
            "hl.plugin.load('/usr/lib/hyprland/hyprexpo.so')\n"
            "hl.plugin.load('/home/me/.local/share/plug.so')\n",
        )
        assert _keywords(load_lua(path), "plugin") == [
            "/usr/lib/hyprland/hyprexpo.so",
            "/home/me/.local/share/plug.so",
        ]

    def test_window_rule_with_match(self, tmp_path: Path) -> None:
        # The Lua reader builds structured Rule nodes directly — no
        # detour through a Hyprlang-stringified intermediate.
        path = _write_lua(
            tmp_path,
            "hl.window_rule({ match = { class = '^kitty$' }, float = true })",
        )
        rules = _rules(load_lua(path), "windowrule")
        assert len(rules) == 1
        assert rules[0].name == ""
        assert rules[0].enabled is True
        assert rules[0].matchers == [("class", "^kitty$")]
        assert rules[0].effects == [("float", "on")]

    def test_layer_rule(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            "hl.layer_rule({ match = { namespace = '^waybar$' }, blur = true })",
        )
        rules = _rules(load_lua(path), "layerrule")
        assert len(rules) == 1
        assert rules[0].matchers == [("namespace", "^waybar$")]
        assert rules[0].effects == [("blur", "on")]

    def test_window_rule_with_name(self, tmp_path: Path) -> None:
        # Regression test for hyprmod issue #37's Lua sibling case: a
        # named Lua rule must land as ONE Rule node with name=Ahoj,
        # not as multiple anonymous rules with ``name`` mis-parsed as
        # an effect (the bug the synthetic-token detour used to mask).
        path = _write_lua(
            tmp_path,
            "hl.window_rule({ name = 'Ahoj', match = { class = '^kitty$' }, float = true })",
        )
        rules = _rules(load_lua(path), "windowrule")
        assert len(rules) == 1
        assert rules[0].name == "Ahoj"
        assert rules[0].effects == [("float", "on")]

    def test_window_rule_disabled(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            "hl.window_rule({ name = 'Off', enabled = false, match = { class = '^x$' }, "
            "float = true })",
        )
        rules = _rules(load_lua(path), "windowrule")
        assert len(rules) == 1
        assert rules[0].name == "Off"
        assert rules[0].enabled is False


class TestBindCalls:
    def test_simple_bind(self, tmp_path: Path) -> None:
        path = _write_lua(tmp_path, "hl.bind('SUPER + Q', hl.dsp.window.close())")
        assert _keywords(load_lua(path), "bind") == ["SUPER, Q, killactive"]

    def test_bind_with_exec(self, tmp_path: Path) -> None:
        path = _write_lua(tmp_path, "hl.bind('SUPER + return', hl.dsp.exec_cmd('kitty'))")
        assert _keywords(load_lua(path), "bind") == ["SUPER, return, exec, kitty"]

    def test_bind_with_multiple_mods(self, tmp_path: Path) -> None:
        path = _write_lua(tmp_path, "hl.bind('SUPER + SHIFT + Q', hl.dsp.window.close())")
        # Hyprlang separates mods with spaces (not commas) — anything else
        # round-trips into a different bind when re-parsed.
        assert _keywords(load_lua(path), "bind") == ["SUPER SHIFT, Q, killactive"]

    def test_bind_with_flags(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            "hl.bind('XF86AudioMute', hl.dsp.exec_cmd('mute'), { locked=true, repeating=true })",
        )
        # bindel = repeating(e) + locked(l), suffix chars sorted.
        assert _keywords(load_lua(path), "bindel") == [", XF86AudioMute, exec, mute"]

    def test_bindm_mouse(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            "hl.bind('SUPER + mouse:272', hl.dsp.window.drag(), { mouse=true })",
        )
        # bindm without a trailing comma — Hyprland rejects ``bindm = …, movewindow,``
        # with "too many args".
        assert _keywords(load_lua(path), "bindm") == ["SUPER, mouse:272, movewindow"]

    def test_bind_movefocus(self, tmp_path: Path) -> None:
        path = _write_lua(tmp_path, "hl.bind('SUPER + left', hl.dsp.focus({ direction = 'left' }))")
        assert _keywords(load_lua(path), "bind") == ["SUPER, left, movefocus, l"]

    def test_bind_workspace_relative(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            "hl.bind('SUPER + mouse_up', hl.dsp.focus({ workspace = 'e+1' }))",
        )
        assert _keywords(load_lua(path), "bind") == ["SUPER, mouse_up, workspace, e+1"]

    def test_bind_movetoworkspace_silent(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            "hl.bind('SUPER + 2', hl.dsp.window.move({ workspace = 2, silent = true }))",
        )
        assert _keywords(load_lua(path), "bind") == ["SUPER, 2, movetoworkspacesilent, 2"]

    def test_bind_movewindow_pixel_absolute(self, tmp_path: Path) -> None:
        # Lua's ``{x, y}`` is absolute by default; Hyprlang spells that as
        # the ``exact`` prefix.
        path = _write_lua(
            tmp_path,
            "hl.bind('SUPER + Q', hl.dsp.window.move({ x = 100, y = 200 }))",
        )
        assert _keywords(load_lua(path), "bind") == ["SUPER, Q, movewindowpixel, exact 100 200"]

    def test_bind_movewindow_pixel_relative(self, tmp_path: Path) -> None:
        # ``relative = true`` switches to a pixel delta; Hyprlang's bare
        # ``X Y`` form (without ``exact``) is the relative case.
        path = _write_lua(
            tmp_path,
            "hl.bind('SUPER + Q', hl.dsp.window.move({ x = 10, y = -5, relative = true }))",
        )
        assert _keywords(load_lua(path), "bind") == ["SUPER, Q, movewindowpixel, 10 -5"]

    def test_bind_togglefloating(self, tmp_path: Path) -> None:
        path = _write_lua(
            tmp_path,
            "hl.bind('SUPER + V', hl.dsp.window.float({ action = 'toggle' }))",
        )
        assert _keywords(load_lua(path), "bind") == ["SUPER, V, togglefloating"]

    def test_bind_global_shortcut(self, tmp_path: Path) -> None:
        path = _write_lua(tmp_path, "hl.bind('SUPER + period', hl.dsp.global('caelestia:emoji'))")
        assert _keywords(load_lua(path), "bind") == ["SUPER, period, global, caelestia:emoji"]

    def test_bind_namespace_as_shorthand_dispatcher(self, tmp_path: Path) -> None:
        # ``hl.dsp.workspace(N)`` is the shorthand form some hand-written
        # configs use. The wrapper has to accept both the call-form here
        # AND the dotted form (``hl.dsp.workspace.toggle_special(...)``)
        # without one breaking the other.
        path = _write_lua(
            tmp_path,
            (
                "hl.bind('SUPER + 1', hl.dsp.workspace(1))\n"
                "hl.bind('SUPER + S', hl.dsp.workspace.toggle_special('scratch'))\n"
            ),
        )
        binds = _keywords(load_lua(path), "bind")
        assert binds == [
            "SUPER, 1, workspace, 1",
            "SUPER, S, togglespecialworkspace, scratch",
        ]

    def test_for_loop_unrolled(self, tmp_path: Path) -> None:
        # The real test of running real Lua: a loop should produce N records.
        path = _write_lua(
            tmp_path,
            """
            local mainMod = 'SUPER'
            for i = 1, 3 do
                hl.bind(mainMod .. ' + ' .. i, hl.dsp.focus({ workspace = i }))
            end
            """,
        )
        binds = _keywords(load_lua(path), "bind")
        assert binds == [
            "SUPER, 1, workspace, 1",
            "SUPER, 2, workspace, 2",
            "SUPER, 3, workspace, 3",
        ]


class TestDofileChain:
    def test_dofile_follows_into_subfile(self, tmp_path: Path) -> None:
        (tmp_path / "child.lua").write_text("hl.env('A', '1')\n")
        main = tmp_path / "main.lua"
        main.write_text(f"dofile('{tmp_path / 'child.lua'}')\n")
        assert _keywords(load_lua(main), "env") == ["A, 1"]

    def test_source_name_tracks_origin_file(self, tmp_path: Path) -> None:
        # hyprmod needs to know which file each line came from so it can
        # skip its own managed sidecar when surfacing "external" entries.
        (tmp_path / "child.lua").write_text("hl.env('FROM_CHILD', '1')\n")
        main = tmp_path / "main.lua"
        main.write_text(f"hl.env('FROM_MAIN', '0')\ndofile('{tmp_path / 'child.lua'}')\n")
        doc = load_lua(main)
        by_value = {
            ln.value: ln.source_name for _, ln in doc.iter_lines() if isinstance(ln, Keyword)
        }
        assert by_value["FROM_MAIN, 0"] == str(main)
        assert by_value["FROM_CHILD, 1"] == str(tmp_path / "child.lua")

    def test_nested_dofile(self, tmp_path: Path) -> None:
        (tmp_path / "leaf.lua").write_text("hl.env('X', '1')\n")
        (tmp_path / "mid.lua").write_text(f"dofile('{tmp_path / 'leaf.lua'}')\n")
        (tmp_path / "main.lua").write_text(f"dofile('{tmp_path / 'mid.lua'}')\n")
        assert _keywords(load_lua(tmp_path / "main.lua"), "env") == ["X, 1"]

    def test_dofile_produces_source_node_with_sub_document(self, tmp_path: Path) -> None:
        # The tree shape must mirror what the Hyprlang parser produces
        # for ``source = …`` so consumers iterate either format the same
        # way. A ``dofile("child.lua")`` becomes a :class:`Source` node on
        # the parent whose ``.documents`` holds the parsed sub-Document.
        from hyprland_config import Source

        child = tmp_path / "child.lua"
        child.write_text("hl.env('A', '1')\n")
        main = tmp_path / "main.lua"
        main.write_text(f"dofile('{child}')\n")
        doc = load_lua(main)

        sources = [ln for ln in doc.lines if isinstance(ln, Source)]
        assert len(sources) == 1
        src = sources[0]
        assert src.path_str == str(child)
        assert src.resolved_paths == [child.resolve()]
        assert len(src.documents) == 1
        assert src.documents[0].path == child
        assert any(isinstance(ln, Keyword) and ln.key == "env" for ln in src.documents[0].lines)

    def test_nested_dofile_produces_nested_documents(self, tmp_path: Path) -> None:
        # Source nodes nest just like Hyprlang ``source = …`` chains:
        # main → mid → leaf becomes Source(Source(Keyword)).
        from hyprland_config import Source

        (tmp_path / "leaf.lua").write_text("hl.env('X', '1')\n")
        (tmp_path / "mid.lua").write_text(f"dofile('{tmp_path / 'leaf.lua'}')\n")
        (tmp_path / "main.lua").write_text(f"dofile('{tmp_path / 'mid.lua'}')\n")
        doc = load_lua(tmp_path / "main.lua")

        mid_src = next(ln for ln in doc.lines if isinstance(ln, Source))
        mid_doc = mid_src.documents[0]
        leaf_src = next(ln for ln in mid_doc.lines if isinstance(ln, Source))
        leaf_doc = leaf_src.documents[0]
        assert leaf_doc.path == (tmp_path / "leaf.lua")
        assert any(isinstance(ln, Keyword) and ln.value == "X, 1" for ln in leaf_doc.lines)

    def test_dofile_failure_does_not_abort_parent(self, tmp_path: Path) -> None:
        # A missing sub-file shouldn't take the whole read down — Hyprland
        # itself logs the error and continues, and we want the same UX.
        main = tmp_path / "main.lua"
        main.write_text(
            f"hl.env('A', '1')\ndofile('{tmp_path / 'missing.lua'}')\nhl.env('B', '2')\n"
        )
        assert _keywords(load_lua(main), "env") == ["A, 1", "B, 2"]


class TestRequireChain:
    """``require()`` sub-files read back like ``dofile()`` ones.

    The migrator emits ``require("modules.monitors")`` (the form Hyprland's
    autoreload watches), so the reader has to resolve module names the way
    Hyprland does — against the main config file's directory via
    ``package.path`` — and surface the same Source-node tree.
    """

    def test_require_follows_into_subfile(self, tmp_path: Path) -> None:
        (tmp_path / "child.lua").write_text("hl.env('FROM_CHILD', '1')\n")
        main = tmp_path / "main.lua"
        main.write_text("require('child')\n")
        doc = load_lua(main)
        assert _keywords(doc, "env") == ["FROM_CHILD, 1"]
        # The recorded origin is the resolved file, not the main config.
        source_names = {ln.source_name for _, ln in doc.iter_lines() if isinstance(ln, Keyword)}
        assert str(tmp_path / "child.lua") in source_names

    def test_require_dotted_module_resolves_subdir(self, tmp_path: Path) -> None:
        (tmp_path / "modules").mkdir()
        (tmp_path / "modules" / "monitors.lua").write_text("hl.env('FROM_SUBDIR', '1')\n")
        main = tmp_path / "main.lua"
        main.write_text("require('modules.monitors')\n")
        assert _keywords(load_lua(main), "env") == ["FROM_SUBDIR, 1"]

    def test_nested_require_resolves_against_config_root(self, tmp_path: Path) -> None:
        # a.lua's require must resolve against the main file's dir (the config
        # root), exactly like Hyprland — not relative to a.lua's own dir. If
        # it resolved file-relative, "sub.b" would miss and FROM_B vanish.
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.lua").write_text("hl.env('FROM_B', '1')\n")
        (sub / "a.lua").write_text("require('sub.b')\nhl.env('FROM_A', '1')\n")
        main = tmp_path / "main.lua"
        main.write_text("require('sub.a')\n")
        assert _keywords(load_lua(main), "env") == ["FROM_B, 1", "FROM_A, 1"]

    def test_require_resolves_hyphenated_dropin_name(self, tmp_path: Path) -> None:
        # Migrated `.conf.d` drop-ins keep names like `00-monitors`; require
        # treats the module name as a path, not a Lua identifier, so leading
        # digits and hyphens resolve fine.
        (tmp_path / "hyprland").mkdir()
        (tmp_path / "hyprland" / "00-monitors.lua").write_text("hl.env('FROM_DROPIN', '1')\n")
        main = tmp_path / "main.lua"
        main.write_text("require('hyprland.00-monitors')\n")
        assert _keywords(load_lua(main), "env") == ["FROM_DROPIN, 1"]

    def test_require_resolves_package_init_lua(self, tmp_path: Path) -> None:
        # The second package.path template, "<root>/?/init.lua", lets a
        # require name a directory package.
        (tmp_path / "theme").mkdir()
        (tmp_path / "theme" / "init.lua").write_text("hl.env('FROM_INIT', '1')\n")
        main = tmp_path / "main.lua"
        main.write_text("require('theme')\n")
        assert _keywords(load_lua(main), "env") == ["FROM_INIT, 1"]

    def test_require_produces_source_node_with_sub_document(self, tmp_path: Path) -> None:
        from hyprland_config import Source

        child = tmp_path / "child.lua"
        child.write_text("hl.env('A', '1')\n")
        main = tmp_path / "main.lua"
        main.write_text("require('child')\n")
        doc = load_lua(main)
        sources = [ln for ln in doc.lines if isinstance(ln, Source)]
        assert len(sources) == 1
        assert sources[0].documents[0].path == child


class TestExcludeSourcesOnLuaDocument:
    """``exclude_sources`` must work on flat Lua-derived Documents.

    The Lua reader merges ``dofile`` chains inline (no :class:`Source`
    nodes wrap sub-files), so Source-level exclusion alone misses them.
    hyprmod's "what would this value be without our managed sidecar?"
    flow (``HyprlandState.get_fallback_value``) relies on this — without
    it, removing an override in the GUI falls back to the schema default
    instead of the value the user actually has in their main config.
    """

    def test_get_excludes_lines_from_named_sub_file(self, tmp_path: Path) -> None:
        child = tmp_path / "child.lua"
        child.write_text("hl.config({ general = { gaps_out = 10 } })\n")
        main = tmp_path / "main.lua"
        main.write_text(f"hl.config({{ general = {{ gaps_out = 5 }} }})\ndofile('{child}')\n")
        doc = load_lua(main)
        # Without exclusion, the child (later in evaluation order) wins.
        assert doc.get("general:gaps_out") == "10"
        # Excluding the child file recovers the parent's value — the
        # "what would this be without our sidecar?" semantics hyprmod
        # uses for fallback resolution.
        assert doc.get("general:gaps_out", exclude_sources=frozenset({child.resolve()})) == "5"

    def test_get_returns_default_when_all_sources_excluded(self, tmp_path: Path) -> None:
        child = tmp_path / "child.lua"
        child.write_text("hl.config({ general = { gaps_out = 10 } })\n")
        main = tmp_path / "main.lua"
        main.write_text(f"dofile('{child}')\n")
        doc = load_lua(main)
        excluded = frozenset({child.resolve()})
        assert doc.get("general:gaps_out", exclude_sources=excluded) is None

    def test_get_unchanged_when_excluded_path_unrelated(self, tmp_path: Path) -> None:
        child = tmp_path / "child.lua"
        child.write_text("hl.config({ general = { gaps_out = 10 } })\n")
        main = tmp_path / "main.lua"
        main.write_text(f"dofile('{child}')\n")
        doc = load_lua(main)
        unrelated = frozenset({(tmp_path / "nothing.lua").resolve()})
        # An exclude_sources entry that matches no line should be a no-op.
        assert doc.get("general:gaps_out", exclude_sources=unrelated) == "10"

    def test_find_all_respects_exclude_sources(self, tmp_path: Path) -> None:
        # Repeated keywords (env / bind / monitor) flow through
        # ``find_all`` rather than ``get``; same exclude semantics.
        child = tmp_path / "child.lua"
        child.write_text("hl.env('FROM_CHILD', '1')\n")
        main = tmp_path / "main.lua"
        main.write_text(f"hl.env('FROM_MAIN', '0')\ndofile('{child}')\n")
        doc = load_lua(main)
        values = [
            ln.value for ln in doc.find_all("env", exclude_sources=frozenset({child.resolve()}))
        ]
        assert values == ["FROM_MAIN, 0"]


class TestErrors:
    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(LuaReaderError, match="lua failed to load"):
            load_lua(tmp_path / "does_not_exist.lua")

    def test_missing_require_ignored(self, tmp_path: Path) -> None:
        src = 'require("missing_module")\nhl.config({ general = { gaps_in = 5 } })\n'
        doc = load_lua(_write_lua(tmp_path, src))
        assert _assignments(doc) == {"general:gaps_in": "5"}

    def test_plugin_namespace_ignored(self, tmp_path: Path) -> None:
        src = (
            "if hl.plugin.some_plugin then\n"
            "    hl.plugin.some_plugin.some_setting = 1\n"
            "end\n"
            "hl.config({ general = { gaps_in = 5 } })\n"
        )
        doc = load_lua(_write_lua(tmp_path, src))
        assert _assignments(doc) == {"general:gaps_in": "5"}

    def test_syntax_error_surfaces(self, tmp_path: Path) -> None:
        path = _write_lua(tmp_path, "this is not valid lua {{{\n")
        with pytest.raises(LuaReaderError):
            load_lua(path)


class TestRoundTripWithEmitter:
    """``parse_string`` → ``serialize_lua`` → ``load_lua`` keeps the
    same option set."""

    @staticmethod
    def _via_lua(src: str, tmp_path: Path):
        emitted = serialize_lua(parse_string(src))
        path = tmp_path / "rt.lua"
        path.write_text(emitted)
        return load_lua(path)

    def test_round_trip_options(self, tmp_path: Path) -> None:
        src = (
            "general:gaps_in = 5\n"
            "decoration:rounding = 10\n"
            "decoration:blur:size = 3\n"
            "misc:vrr = true\n"
        )
        doc = self._via_lua(src, tmp_path)
        assert _assignments(doc) == {
            "general:gaps_in": "5",
            "decoration:rounding": "10",
            "decoration:blur:size": "3",
            "misc:vrr": "true",
        }

    def test_round_trip_env_and_bezier_and_animation(self, tmp_path: Path) -> None:
        src = (
            "env = XCURSOR_SIZE, 24\n"
            "bezier = easeOut, 0.05, 0.9, 0.1, 1.05\n"
            "animation = windows, 1, 7, easeOut, slide\n"
        )
        doc = self._via_lua(src, tmp_path)
        assert _keywords(doc, "env") == ["XCURSOR_SIZE, 24"]
        assert _keywords(doc, "bezier") == ["easeOut, 0.05, 0.9, 0.1, 1.05"]
        # Round-trip normalises the legacy ``1`` to the canonical ``true``.
        assert _keywords(doc, "animation") == ["windows, true, 7, easeOut, slide"]

    def test_round_trip_exec_and_exec_shutdown(self, tmp_path: Path) -> None:
        # The three exec keywords carry distinct semantics that survive the
        # round-trip: ``exec`` lands at top-level (re-runs on every reload
        # via file re-evaluation); ``exec-once`` nests in an
        # ``hl.on("hyprland.start", …)`` block (fires once at session
        # startup); ``exec-shutdown`` nests in the matching shutdown block.
        src = "exec = waybar\nexec-once = nm-applet\nexec-shutdown = sync\n"
        doc = self._via_lua(src, tmp_path)
        assert _keywords(doc, "exec") == ["waybar"]
        assert _keywords(doc, "exec-once") == ["nm-applet"]
        assert _keywords(doc, "exec-shutdown") == ["sync"]

    def test_round_trip_multi_file_tree(self, tmp_path: Path) -> None:
        (tmp_path / "binds.conf").write_text(
            "bind = SUPER, Q, killactive,\nbind = SUPER, return, exec, kitty\n"
        )
        (tmp_path / "general.conf").write_text("general:gaps_in = 5\nmisc:vrr = 1\n")
        main = tmp_path / "hyprland.conf"
        main.write_text(
            f"source = {tmp_path / 'binds.conf'}\nsource = {tmp_path / 'general.conf'}\n"
        )
        from hyprland_config import load

        tree = serialize_lua_tree(load(main))
        # Write the emitted files to their natural paths next to the .conf.
        for entry in tree:
            entry.path.write_text(entry.content)

        doc = load_lua(main.with_suffix(".lua"))
        assert _keywords(doc, "bind")[:2] == [
            "SUPER, Q, killactive",
            "SUPER, return, exec, kitty",
        ]
        assert _assignments(doc)["general:gaps_in"] == "5"
