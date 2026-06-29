"""Lua bind emitters, dispatcher translation, and live-apply helpers.

Covers the ``bind`` family (``bind`` / ``binde`` / ``bindm`` / ``bindd`` / …),
the dispatcher mapping table, the ``hyprctl keyword`` shell-out translation,
and the runtime APIs ``dispatch_to_lua`` and ``define_submap_to_lua``.
"""

import pytest

from hyprland_config import parse_string, serialize_lua
from hyprland_config._lua import define_submap_to_lua, dispatch_to_lua, emit_keyword_line
from tests._lua_helpers import assert_lua_compiles, requires_lua


class TestBindBasic:
    def test_bind_exec_maps_to_dsp_exec_cmd(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, Return, exec, kitty\n"))
        assert 'hl.bind("SUPER + Return", hl.dsp.exec_cmd("kitty"))' in out

    def test_bind_killactive_maps_to_window_close(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, Q, killactive,\n"))
        assert 'hl.bind("SUPER + Q", hl.dsp.window.close())' in out

    def test_bind_with_multiple_mods(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER SHIFT, Q, killactive,\n"))
        assert 'hl.bind("SUPER + SHIFT + Q"' in out

    def test_bind_with_no_mods(self) -> None:
        out = serialize_lua(parse_string("bind = , XF86AudioMute, exec, mute\n"))
        assert 'hl.bind("XF86AudioMute"' in out

    def test_bind_exit(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, M, exit,\n"))
        assert "hl.dsp.exit()" in out


class TestModifierNormalization:
    """Hyprlang accepted concatenated / mixed-case modifiers; Lua needs exact
    uppercase tokens. Legacy ``stringToModMask`` uppercased the whole mods
    field and substring-matched each name, so ``SUPERSHIFT`` and ``Alt`` both
    worked. ``hl.bind`` reads anything that isn't an exact mod token as a
    keysym (``Unknown keysym: "SUPERSHIFT"``), so we decompose on the way out.
    """

    def test_concatenated_mods_split(self) -> None:
        out = serialize_lua(parse_string("bind = SUPERSHIFT, F, fullscreen\n"))
        assert 'hl.bind("SUPER + SHIFT + F"' in out
        assert "SUPERSHIFT" not in out

    def test_lowercase_mods_uppercased(self) -> None:
        out = serialize_lua(parse_string("bind = Alt, F4, killactive,\n"))
        assert 'hl.bind("ALT + F4"' in out

    def test_mixed_case_concatenated(self) -> None:
        out = serialize_lua(parse_string("bind = SuperShift, Q, killactive,\n"))
        assert 'hl.bind("SUPER + SHIFT + Q"' in out

    def test_underscore_separated_mods_split(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER_SHIFT, Q, killactive,\n"))
        assert 'hl.bind("SUPER + SHIFT + Q"' in out

    def test_control_alias_canonicalized(self) -> None:
        out = serialize_lua(parse_string("bind = CONTROLALT, Delete, exec, logout\n"))
        assert 'hl.bind("CTRL + ALT + Delete"' in out

    def test_already_canonical_unchanged(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER SHIFT, Q, killactive,\n"))
        assert 'hl.bind("SUPER + SHIFT + Q"' in out

    def test_var_mod_preserved_alongside_literal(self) -> None:
        # ``$mainMod`` must survive as the ``var_mainMod`` reference, not get
        # mistaken for a modifier blob and torn apart.
        out = serialize_lua(
            parse_string("$mainMod = SUPER\nbind = $mainMod SHIFT, Q, killactive,\n")
        )
        assert 'var_mainMod .. " + SHIFT + Q"' in out


class TestModifierComboVariables:
    """A variable whose value is a modifier combo (``$shiftMod = $mainMod SHIFT``)
    must re-join with `` + `` in its definition. Without it the variable expands
    to the space-separated ``SUPER SHIFT`` blob, which ``hl.bind`` reads as a
    single unknown keysym. https://github.com/BlueManCZ/hyprmod/issues/52
    """

    def test_var_plus_literal_modifier_joins_with_plus(self) -> None:
        out = serialize_lua(
            parse_string(
                "$mainMod = SUPER\n$shiftMod = $mainMod SHIFT\nbind = $shiftMod, Q, killactive,\n"
            )
        )
        assert 'var_shiftMod = var_mainMod .. " + SHIFT"' in out

    def test_nested_modifier_var_resolves_recursively(self) -> None:
        out = serialize_lua(
            parse_string(
                "$mainMod = SUPER\n$shiftMod = $mainMod SHIFT\n$ctrlMod = $shiftMod CTRL\n"
                "bind = $ctrlMod, Q, killactive,\n"
            )
        )
        assert 'var_ctrlMod = var_shiftMod .. " + CTRL"' in out

    def test_single_modifier_var_unchanged(self) -> None:
        # One token needs no joining; the bare string stays as-is.
        out = serialize_lua(parse_string("$mainMod = SUPER\nbind = $mainMod, Q, killactive,\n"))
        assert 'var_mainMod = "SUPER"' in out

    def test_non_modifier_multiword_var_keeps_spaces(self) -> None:
        # ``$term`` is a command, not a modmask — its spaces must survive.
        out = serialize_lua(
            parse_string("$term = kitty --class foo\nbind = SUPER, Return, exec, $term\n")
        )
        assert 'var_term = "kitty --class foo"' in out


class TestBindFlags:
    def test_binde_repeating(self) -> None:
        out = serialize_lua(parse_string("binde = , XF86AudioRaiseVolume, exec, up\n"))
        assert "repeating = true" in out

    def test_bindl_locked(self) -> None:
        out = serialize_lua(parse_string("bindl = , XF86AudioMute, exec, mute\n"))
        assert "locked = true" in out

    def test_bindm_mouse(self) -> None:
        out = serialize_lua(parse_string("bindm = SUPER, mouse:272, movewindow\n"))
        assert "mouse = true" in out
        assert "hl.dsp.window.drag()" in out

    def test_bindr_release(self) -> None:
        out = serialize_lua(parse_string("bindr = SUPER, Q, killactive,\n"))
        assert "release = true" in out

    def test_combined_bindel(self) -> None:
        # Both repeating and locked.
        out = serialize_lua(parse_string("bindel = , XF86AudioMute, exec, mute\n"))
        assert "repeating = true" in out
        assert "locked = true" in out

    def test_unknown_flag_punts_to_todo(self) -> None:
        # `s` / `d` / `p` aren't in the supported flag map yet.
        out = serialize_lua(parse_string("binds = SUPER, Q, killactive,\n"))
        assert "-- TODO" in out
        assert "binds = SUPER, Q" in out


class TestBindDispatchers:
    def test_movefocus_direction(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, left, movefocus, l\n"))
        assert 'hl.dsp.focus({ direction = "left" })' in out

    def test_workspace_numeric(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, 1, workspace, 1\n"))
        assert "hl.dsp.focus({ workspace = 1 })" in out

    def test_workspace_relative(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, mouse_down, workspace, e+1\n"))
        assert 'hl.dsp.focus({ workspace = "e+1" })' in out

    def test_movetoworkspace(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER SHIFT, 1, movetoworkspace, 1\n"))
        assert "hl.dsp.window.move({ workspace = 1 })" in out

    def test_movetoworkspacesilent(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, 2, movetoworkspacesilent, 2\n"))
        assert "silent = true" in out

    def test_togglespecialworkspace(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, S, togglespecialworkspace, magic\n"))
        assert 'hl.dsp.workspace.toggle_special("magic")' in out

    def test_togglefloating(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, V, togglefloating,\n"))
        assert 'hl.dsp.window.float({ action = "toggle" })' in out

    def test_layoutmsg(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, J, layoutmsg, togglesplit\n"))
        assert 'hl.dsp.layout("togglesplit")' in out

    def test_global_shortcut(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, period, global, caelestia:emoji\n"))
        assert 'hl.bind("SUPER + period", hl.dsp.global("caelestia:emoji"))' in out

    def test_unknown_dispatcher_punts_to_todo(self) -> None:
        # Hyprland's wiki doesn't document a generic legacy-dispatcher escape
        # hatch in the Lua API. Rather than invent one (e.g. wrapping the
        # call in ``hyprctl dispatch …``), we leave the bind in the
        # manual-conversion block so the user knows to port it explicitly.
        out = serialize_lua(parse_string("bind = SUPER, X, mysteryaction, foo\n"))
        assert "hl.bind" not in out
        assert "-- TODO" in out
        assert "bind = SUPER, X, mysteryaction, foo" in out

    def test_workspaceopt_lands_in_todo(self) -> None:
        # No documented ``hl.dsp.workspaceopt`` in 0.55.0.
        out = serialize_lua(parse_string("bind = SUPER, V, workspaceopt, allfloat\n"))
        assert "-- TODO" in out
        assert "workspaceopt, allfloat" in out

    def test_bindm_resize(self) -> None:
        out = serialize_lua(parse_string("bindm = SUPER, mouse:273, resizewindow\n"))
        assert "hl.dsp.window.resize()" in out


class TestExtraDispatchers:
    """Less common dispatchers found in real configs."""

    def test_focuscurrentorlast(self) -> None:
        out = serialize_lua(parse_string("bind = ALT, tab, focuscurrentorlast\n"))
        assert "hl.dsp.focus({ last = true })" in out

    def test_changegroupactive_forward(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, n, changegroupactive, f\n"))
        assert "hl.dsp.group.next()" in out

    def test_changegroupactive_back(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, p, changegroupactive, b\n"))
        assert "hl.dsp.group.prev()" in out

    def test_moveoutofgroup(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, g, moveoutofgroup\n"))
        assert "hl.dsp.window.move({ out_of_group = true })" in out

    def test_moveintogroup(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, l, moveintogroup, l\n"))
        assert 'hl.dsp.window.move({ into_group = "left" })' in out

    def test_resizeactive_relative(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, l, resizeactive, 50 0\n"))
        assert "hl.dsp.window.resize({ x = 50, y = 0, relative = true })" in out

    def test_resizeactive_exact(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, l, resizeactive, exact 800 600\n"))
        assert "hl.dsp.window.resize({ x = 800, y = 600 })" in out
        assert "relative" not in out

    def test_setprop_two_arg(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, p, setprop, opaque toggle\n"))
        assert 'prop = "opaque"' in out
        assert 'value = "toggle"' in out

    def test_setprop_with_window_selector(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, p, setprop, active opaque toggle\n"))
        assert 'window = "active"' in out

    def test_movecurrentworkspacetomonitor(self) -> None:
        out = serialize_lua(
            parse_string("bind = SUPER CTRL, F9, movecurrentworkspacetomonitor, l\n")
        )
        assert 'hl.dsp.workspace.move({ monitor = "l" })' in out

    def test_changegroupactive_no_arg_cycles_next(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, tab, changegroupactive,\n"))
        assert "hl.dsp.group.next()" in out


class TestBindd:
    """The ``bindd`` family carries an extra description field.

    Layout: ``bindd = MODS, KEY, DESCRIPTION, DISPATCHER [, ARG]``. The
    description becomes a string ``description`` flag on the Lua bind;
    real-world configs (JaKooLit's, etc.) lean heavily on this for
    populating cheat-sheet overlays.
    """

    def test_bindd_emits_description_flag(self) -> None:
        out = serialize_lua(parse_string("bindd = SUPER, D, app launcher, exec, rofi -show drun\n"))
        assert 'description = "app launcher"' in out
        assert 'hl.bind("SUPER + D", hl.dsp.exec_cmd("rofi -show drun")' in out

    def test_bindd_with_quoted_command_arg(self) -> None:
        out = serialize_lua(
            parse_string('bindd = SUPER, B, open browser, exec, xdg-open "https://"\n')
        )
        assert 'description = "open browser"' in out

    def test_binded_combines_repeating_and_description(self) -> None:
        out = serialize_lua(
            parse_string("binded = SUPER SHIFT, left, resize left, resizeactive, -50 0\n")
        )
        assert "repeating = true" in out
        assert 'description = "resize left"' in out
        assert "hl.dsp.window.resize({ x = -50, y = 0, relative = true })" in out

    def test_bindmd_combines_mouse_and_description(self) -> None:
        out = serialize_lua(parse_string("bindmd = SUPER, mouse:272, move window, movewindow\n"))
        assert "mouse = true" in out
        assert 'description = "move window"' in out
        assert "hl.dsp.window.drag()" in out


class TestHyprctlKeywordTranslation:
    """``exec, hyprctl keyword …`` → native ``hl.config`` calls.

    The ``keyword`` IPC verb is rejected in Lua mode, so a passthrough
    shell-out would silently break the bind after migration. The
    converter translates the shape it recognises and falls back to the
    original ``hl.exec_cmd`` / ``hl.dsp.exec_cmd`` form for anything
    else.
    """

    # ---- bind dispatcher form -------------------------------------------

    def test_bind_exec_hyprctl_keyword_becomes_closure(self) -> None:
        out = serialize_lua(
            parse_string("bind = SUPER, mouse:272, exec, hyprctl keyword dwindle:smart_split 1\n")
        )
        assert 'hl.bind("SUPER + mouse:272", function()' in out
        assert "hl.config({" in out
        assert "dwindle = {" in out
        assert "smart_split = 1," in out
        # The original shell-out path must NOT appear — that's the bug
        # we're fixing.
        assert "hl.dsp.exec_cmd" not in out
        assert "hyprctl keyword" not in out

    def test_bindr_release_flag_preserved_with_closure(self) -> None:
        out = serialize_lua(
            parse_string("bindr = SUPER, mouse:272, exec, hyprctl keyword dwindle:smart_split 0\n")
        )
        assert "function()" in out
        assert "smart_split = 0," in out
        assert "release = true," in out

    def test_bindm_mouse_flag_preserved_with_closure(self) -> None:
        out = serialize_lua(
            parse_string("bindm = SUPER, mouse:272, exec, hyprctl keyword general:gaps_in 5\n")
        )
        assert "function()" in out
        assert "mouse = true," in out
        assert "gaps_in = 5," in out

    def test_bindd_description_preserved_with_closure(self) -> None:
        line = "bindd = SUPER, S, toggle smart split, exec, hyprctl keyword dwindle:smart_split 1\n"
        out = serialize_lua(parse_string(line))
        assert 'description = "toggle smart split"' in out
        assert "function()" in out
        assert "hl.config({" in out

    def test_deeply_nested_key_path(self) -> None:
        out = serialize_lua(
            parse_string("bind = SUPER, B, exec, hyprctl keyword decoration:blur:size 8\n")
        )
        assert "decoration = {" in out
        assert "blur = {" in out
        assert "size = 8," in out

    def test_dot_subprefix_treated_as_nesting(self) -> None:
        line = (
            'bind = SUPER, C, exec, hyprctl keyword general:col.inactive_border "rgba(595959aa)"\n'
        )
        out = serialize_lua(parse_string(line))
        # ``col.inactive_border`` nests the same way the static keyword
        # emitter handles it: general → col → inactive_border.
        assert "general = {" in out
        assert "col = {" in out
        assert 'inactive_border = "rgba(595959aa)"' in out

    def test_value_coercion_bool(self) -> None:
        out = serialize_lua(
            parse_string("bind = SUPER, X, exec, hyprctl keyword cursor:no_hardware_cursors true\n")
        )
        assert "no_hardware_cursors = true," in out

    def test_value_coercion_float(self) -> None:
        out = serialize_lua(
            parse_string("bind = SUPER, X, exec, hyprctl keyword decoration:active_opacity 0.95\n")
        )
        assert "active_opacity = 0.95," in out

    def test_hyprctl_dispatch_collapses_to_native_dispatcher(self) -> None:
        # ``hyprctl dispatch`` is reparsed as ``hl.dispatch(<ARG>)`` in
        # Lua mode (0.55+), so the legacy space-separated form fails.
        # Whole-command shape collapses to the native dispatcher,
        # bypassing the shell roundtrip.
        out = serialize_lua(
            parse_string("bind = SUPER, T, exec, hyprctl dispatch togglefloating\n")
        )
        assert 'hl.bind("SUPER + T", hl.dsp.window.float({ action = "toggle" }))' in out
        assert "hl.dsp.exec_cmd(" not in out

    def test_hyprctl_dispatch_dpms_whole_command(self) -> None:
        out = serialize_lua(parse_string("bind = SUPER, L, exec, hyprctl dispatch dpms off\n"))
        assert 'hl.bind("SUPER + L", hl.dsp.dpms("off"))' in out

    def test_hyprctl_dispatch_with_instance_flag(self) -> None:
        # ``--instance N`` (and the ``-i`` short form) takes a value; the
        # parser must skip past it to find ``dispatch``.
        out = serialize_lua(
            parse_string("bind = SUPER, L, exec, hyprctl --instance 0 dispatch dpms off\n")
        )
        assert 'hl.bind("SUPER + L", hl.dsp.dpms("off"))' in out

    def test_hyprctl_dispatch_embedded_in_shell_left_verbatim(self) -> None:
        # ``hyprctl dispatch`` embedded in a larger shell command is a runtime
        # IPC call to the ``hyprctl`` binary — it behaves identically whether
        # the config is Hyprlang or Lua. Rewriting it to Lua dispatch syntax
        # would break it, so the whole shell string (timing wrapper and all)
        # passes through verbatim.
        out = serialize_lua(
            parse_string(
                "bind = SUPER, L, exec, sleep 1 && hyprctl --instance 0 dispatch dpms off\n"
            )
        )
        assert 'hl.dsp.exec_cmd("sleep 1 && hyprctl --instance 0 dispatch dpms off")' in out
        assert "hl.dsp.dpms" not in out

    def test_bind_exec_embedded_dispatch_not_mangled(self) -> None:
        # hyprmod issue #45: an embedded ``hyprctl dispatch exit`` inside a
        # larger shell command must stay a literal runtime shell-out. The old
        # rewrite turned it into ``hyprctl dispatch 'hl.dsp.exit()'`` — which
        # hyprctl can't parse — silently breaking the keybind.
        out = serialize_lua(
            parse_string(
                "$mainMod = SUPER\n"
                "bind = $mainMod, M, exec, command -v hyprshutdown >/dev/null 2>&1 "
                "&& hyprshutdown || hyprctl dispatch exit\n"
            )
        )
        assert "hyprctl dispatch exit" in out
        assert "hl.dsp.exit()" not in out

    def test_hyprctl_dispatch_unknown_verb_left_alone(self) -> None:
        # A verb that has no native translation isn't second-guessed; the
        # original shell text passes through to ``hl.dsp.exec_cmd``.
        out = serialize_lua(
            parse_string("bind = SUPER, L, exec, hyprctl dispatch madeupverb foo\n")
        )
        assert 'hl.dsp.exec_cmd("hyprctl dispatch madeupverb foo")' in out

    def test_bind_dpms_direct(self) -> None:
        # ``dpms`` as a direct dispatcher (not wrapped in exec/hyprctl)
        # used to land in the manual-conversion block; now it maps to
        # ``hl.dsp.dpms`` like any other dispatcher.
        out = serialize_lua(parse_string("bind = SUPER, L, dpms, off\n"))
        assert 'hl.bind("SUPER + L", hl.dsp.dpms("off"))' in out

    def test_hyprctl_batch_falls_through_to_exec_cmd(self) -> None:
        # ``--batch`` payloads with embedded ``keyword`` would silently
        # break, but splitting them is out of scope. Falling through is
        # honest — the user sees the unchanged shell-out.
        out = serialize_lua(
            parse_string('bind = SUPER, X, exec, hyprctl --batch "keyword X:Y 1 ; keyword A:B 2"\n')
        )
        assert "hl.dsp.exec_cmd(" in out
        assert "--batch" in out

    def test_non_namespaced_keyword_falls_through(self) -> None:
        # ``hyprctl keyword bind "SUPER, X, exec, kitty"`` would need
        # an ``hl.bind`` re-emit, not an ``hl.config`` call. Out of
        # scope for now — falls through to the shell-out form.
        out = serialize_lua(
            parse_string('bind = SUPER, X, exec, hyprctl keyword bind "SUPER, Y, exec, kitty"\n')
        )
        assert "hl.dsp.exec_cmd(" in out
        assert "hl.config(" not in out

    def test_arbitrary_exec_unchanged(self) -> None:
        # Non-hyprctl execs keep the existing dispatcher form.
        out = serialize_lua(parse_string("bind = SUPER, Return, exec, kitty\n"))
        assert 'hl.dsp.exec_cmd("kitty")' in out
        assert "hl.config(" not in out

    # ---- top-level exec keyword ------------------------------------------

    def test_top_level_exec_hyprctl_keyword_becomes_hl_config(self) -> None:
        # ``exec`` runs on every reload, so the translated ``hl.config``
        # call sits at top level (not wrapped in any ``hl.on`` block).
        out = serialize_lua(parse_string("exec = hyprctl keyword decoration:rounding 10\n"))
        assert 'hl.on("hyprland.start"' not in out
        assert "hl.config({" in out
        assert "rounding = 10," in out
        # The literal shell-out must not appear.
        assert "hyprctl keyword" not in out
        assert "hl.exec_cmd" not in out

    def test_top_level_exec_once_hyprctl_keyword_becomes_hl_config(self) -> None:
        # ``exec-once`` still translates the ``hyprctl keyword`` shell-out
        # to an ``hl.config`` call, just nested inside the start block.
        out = serialize_lua(parse_string("exec-once = hyprctl keyword decoration:rounding 10\n"))
        assert 'hl.on("hyprland.start", function()' in out
        assert "hl.config({" in out
        assert "rounding = 10," in out
        assert "hyprctl keyword" not in out
        assert "TODO: was exec-once" not in out

    def test_top_level_exec_once_emits_in_hl_on_block(self) -> None:
        # Plain ``exec-once = COMMAND`` (no hyprctl) wraps in
        # ``hl.on("hyprland.start", …)`` whose callback fires only at
        # session startup — the Lua equivalent of Hyprlang's run-once
        # semantics.
        out = serialize_lua(parse_string("exec-once = waybar\n"))
        assert 'hl.on("hyprland.start", function()' in out
        assert 'hl.exec_cmd("waybar")' in out
        # No migration marker — the distinction is preserved in the shape.
        assert "TODO: was exec-once" not in out

    def test_top_level_exec_shutdown_translates(self) -> None:
        out = serialize_lua(
            parse_string("exec-shutdown = hyprctl keyword cursor:no_hardware_cursors false\n")
        )
        assert 'hl.on("hyprland.shutdown", function()' in out
        assert "no_hardware_cursors = false," in out

    def test_top_level_exec_hyprctl_dispatch_uses_hl_dispatch(self) -> None:
        # ``hyprctl dispatch VERB ARGS`` collapses to a native
        # ``hl.dispatch(hl.dsp.*())`` call — no shell hop needed.
        out = serialize_lua(parse_string("exec = hyprctl dispatch dpms on\n"))
        assert 'hl.dispatch(hl.dsp.dpms("on"))' in out
        assert "hyprctl dispatch" not in out

    def test_top_level_exec_hyprctl_dispatch_embedded_left_verbatim(self) -> None:
        # Embedded ``hyprctl dispatch`` is a runtime shell-out; it stays
        # verbatim rather than being mangled into Lua dispatch syntax.
        out = serialize_lua(parse_string("exec = sleep 1 && hyprctl dispatch dpms on\n"))
        assert 'hl.exec_cmd("sleep 1 && hyprctl dispatch dpms on")' in out
        assert "hl.dsp.dpms" not in out

    def test_mixed_exec_lines_emit_in_source_order(self) -> None:
        # ``exec`` emits at top level — when multiple ``exec`` entries
        # interleave shell-out and translated-keyword calls, they preserve
        # source order rather than getting batched into one block.
        out = serialize_lua(
            parse_string(
                "exec = waybar\nexec = hyprctl keyword decoration:rounding 10\nexec = nm-applet\n"
            )
        )
        assert 'hl.on("hyprland.start"' not in out
        waybar = out.index('hl.exec_cmd("waybar")')
        config = out.index("hl.config({")
        applet = out.index('hl.exec_cmd("nm-applet")')
        assert waybar < config < applet

    # ---- emit_keyword_line (one-shot live-apply API) ---------------------

    def test_emit_keyword_line_exec_translates(self) -> None:
        out = emit_keyword_line("exec", "hyprctl keyword dwindle:smart_split 1")
        assert out is not None
        assert out.startswith("hl.config(")
        assert "smart_split = 1," in out

    def test_emit_keyword_line_bind_with_exec_keyword_translates(self) -> None:
        out = emit_keyword_line(
            "bind",
            "SUPER, mouse:272, exec, hyprctl keyword dwindle:smart_split 1",
        )
        assert out is not None
        assert "function()" in out
        assert "hl.config({" in out
        assert "hl.dsp.exec_cmd" not in out

    def test_emit_keyword_line_arbitrary_exec_passthrough(self) -> None:
        out = emit_keyword_line("exec", "waybar")
        assert out == 'hl.exec_cmd("waybar")'

    # ---- syntactic validity ---------------------------------------------

    @requires_lua
    def test_emitted_lua_compiles(self) -> None:
        out = serialize_lua(
            parse_string(
                "bind = SUPER, mouse:272, exec, hyprctl keyword dwindle:smart_split 1\n"
                "bindr = SUPER, mouse:272, exec, hyprctl keyword dwindle:smart_split 0\n"
                "bindm = SUPER, mouse:272, exec, hyprctl keyword general:gaps_in 5\n"
                "exec = hyprctl keyword decoration:rounding 10\n"
                "exec-shutdown = hyprctl keyword cursor:no_hardware_cursors false\n"
            )
        )
        assert_lua_compiles(out)


class TestDispatchToLua:
    """``dispatch_to_lua`` produces the live-apply form for ``hyprctl dispatch``.

    Hyprland 0.55's ``hl.dispatch`` takes a dispatcher *value* (an
    ``hl.dsp.*`` call), not a string. We reuse the same translation the
    bind emitter uses and wrap it in ``hl.dispatch(...)`` to execute.
    """

    def test_simple_dispatcher(self) -> None:
        assert dispatch_to_lua("killactive") == "hl.dispatch(hl.dsp.window.close())"

    def test_submap(self) -> None:
        assert dispatch_to_lua("submap", "reset") == 'hl.dispatch(hl.dsp.submap("reset"))'

    def test_workspace(self) -> None:
        assert dispatch_to_lua("workspace", "2") == "hl.dispatch(hl.dsp.focus({ workspace = 2 }))"

    def test_exec_passthrough(self) -> None:
        assert dispatch_to_lua("exec", "waybar") == 'hl.dispatch(hl.dsp.exec_cmd("waybar"))'

    def test_unknown_dispatcher_raises(self) -> None:
        with pytest.raises(ValueError, match="No Lua mapping"):
            dispatch_to_lua("notarealdispatcher", "")

    def test_togglefloating_with_address(self) -> None:
        out = dispatch_to_lua("togglefloating", "address:0xabc")
        assert out == (
            'hl.dispatch(hl.dsp.window.float({ action = "toggle", window = "address:0xabc" }))'
        )

    def test_setprop_with_address(self) -> None:
        out = dispatch_to_lua("setprop", "address:0xabc opacity 0.5")
        assert "hl.dsp.window.set_prop" in out
        assert 'window = "address:0xabc"' in out
        assert 'prop = "opacity"' in out

    def test_movetoworkspacesilent_with_address(self) -> None:
        out = dispatch_to_lua("movetoworkspacesilent", "2,address:0xabc")
        assert out == (
            "hl.dispatch(hl.dsp.window.move({ workspace = 2, silent = true, "
            'window = "address:0xabc" }))'
        )

    def test_movewindow_monitor_with_address(self) -> None:
        out = dispatch_to_lua("movewindow", "mon:DP-1,address:0xabc")
        assert out == (
            'hl.dispatch(hl.dsp.window.move({ monitor = "DP-1", window = "address:0xabc" }))'
        )

    def test_fullscreenstate_with_address(self) -> None:
        out = dispatch_to_lua("fullscreenstate", "2 -1,address:0xabc")
        assert out == (
            "hl.dispatch(hl.dsp.window.fullscreen_state({ internal = 2, client = -1, "
            'window = "address:0xabc" }))'
        )

    def test_movewindowpixel_with_address(self) -> None:
        out = dispatch_to_lua("movewindowpixel", "exact 100 200,address:0xabc")
        assert out == (
            'hl.dispatch(hl.dsp.window.move({ x = 100, y = 200, window = "address:0xabc" }))'
        )

    def test_movewindowpixel_relative(self) -> None:
        out = dispatch_to_lua("movewindowpixel", "10 -20")
        assert out == "hl.dispatch(hl.dsp.window.move({ x = 10, y = -20, relative = true }))"

    def test_address_targeted_unsupported_raises(self) -> None:
        """Dispatchers not in the address-aware allowlist must reject an
        address selector — otherwise their emitter would silently apply
        to the active window."""
        with pytest.raises(ValueError):
            dispatch_to_lua("killactive", "address:0xabc")


class TestDefineSubmapToLua:
    """``define_submap_to_lua`` composes the declarative Lua submap form.

    Hyprlang's stateful ``submap=NAME`` / ``bind=…`` / ``submap=reset``
    sequence collapses to a single ``hl.define_submap(NAME, function() … end)``
    call in Lua — the binds inside have to be supplied up-front.
    """

    def test_single_bind(self) -> None:
        out = define_submap_to_lua("capture", [("bind", ", XF86LaunchA, noop,")])
        assert out.startswith('hl.define_submap("capture", function()\n')
        assert 'hl.bind("XF86LaunchA", hl.dsp.no_op())' in out
        assert out.endswith("\nend)")

    def test_multiple_binds(self) -> None:
        out = define_submap_to_lua(
            "resize",
            [
                ("bind", "SUPER, R, killactive,"),
                ("bind", "SUPER, F, fullscreen,"),
            ],
        )
        assert "hl.dsp.window.close()" in out
        assert "hl.dsp.window.fullscreen()" in out

    def test_empty_binds_raises(self) -> None:
        """Hyprland silently no-ops a submap registration with no binds —
        catch the mistake at translation time instead of letting the user
        wonder why ``hl.dispatch(hl.dsp.submap(NAME))`` reports the
        submap doesn't exist."""
        with pytest.raises(ValueError, match="no binds"):
            define_submap_to_lua("empty", [])

    def test_untranslatable_bind_raises(self) -> None:
        with pytest.raises(ValueError, match="No Lua mapping"):
            define_submap_to_lua("bad", [("bind", "SUPER, K, notarealdispatcher,")])

    def test_name_with_special_characters_quoted(self) -> None:
        out = define_submap_to_lua('with"quote', [("bind", ", XF86LaunchA, noop,")])
        assert r'hl.define_submap("with\"quote"' in out
