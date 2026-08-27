"""Per-keyword Lua emitters — env, monitor, bezier, animation, rules, exec, device."""

import pytest

from hyprland_config import Rule, keyword_to_lua, normalize_rules, parse_string, serialize_lua
from hyprland_config._lua import render_rule_lua


class TestEnvKeyword:
    def test_env_emits_hl_env(self) -> None:
        out = serialize_lua(parse_string("env = XCURSOR_SIZE, 24\n"))
        assert 'hl.env("XCURSOR_SIZE", "24")' in out

    def test_env_with_path_value(self) -> None:
        out = serialize_lua(parse_string("env = GTK_THEME, Adwaita-dark\n"))
        assert 'hl.env("GTK_THEME", "Adwaita-dark")' in out

    def test_multiple_env_lines_kept_separate(self) -> None:
        out = serialize_lua(parse_string("env = A, 1\nenv = B, 2\n"))
        assert 'hl.env("A", "1")' in out
        assert 'hl.env("B", "2")' in out


class TestMonitorKeyword:
    def test_monitor_full_form(self) -> None:
        out = serialize_lua(parse_string("monitor = DP-1, 2560x1440@144, 0x0, 1\n"))
        assert "hl.monitor({" in out
        assert 'output = "DP-1",' in out
        assert 'mode = "2560x1440@144",' in out
        assert 'position = "0x0",' in out
        assert "scale = 1," in out

    def test_monitor_with_float_scale(self) -> None:
        out = serialize_lua(parse_string("monitor = DP-1, preferred, auto, 1.5\n"))
        assert "scale = 1.5," in out

    def test_monitor_extras_parsed_as_kv_pairs(self) -> None:
        # Trailing KEY, VALUE pairs become typed Lua fields.
        out = serialize_lua(
            parse_string("monitor = DP-1, preferred, auto, 1, transform, 3, bitdepth, 10\n")
        )
        assert "transform = 3," in out
        assert "bitdepth = 10," in out

    def test_monitor_extras_with_string_value(self) -> None:
        out = serialize_lua(parse_string("monitor = DP-1, preferred, auto, 1, cm, srgb\n"))
        assert 'cm = "srgb",' in out

    def test_monitor_extras_odd_tail_surfaced(self) -> None:
        # A trailing KEY without a paired VALUE is rare but mustn't be silently dropped.
        out = serialize_lua(parse_string("monitor = DP-1, preferred, auto, 1, weird\n"))
        assert "__unparsed_extra" in out

    def test_monitor_full_form_emits_explicit_enable(self) -> None:
        # ``hl.monitor`` is additive: a sticky ``disabled = true`` from an
        # earlier call survives unless cleared, so a full line must emit
        # ``disabled = false`` to re-enable an output live (legacy Hyprlang
        # re-enables implicitly on a full line).
        out = serialize_lua(parse_string("monitor = DP-1, 2560x1440@144, 0x0, 1\n"))
        assert "disabled = false," in out

    def test_monitor_disable_short_form(self) -> None:
        # ``monitor = OUTPUT, disable`` is Hyprlang's short-form; the Lua API
        # expects ``disabled = true`` and rejects ``mode = "disable"``.
        out = serialize_lua(parse_string("monitor = DP-1, disable\n"))
        assert 'output = "DP-1",' in out
        assert "disabled = true," in out
        assert 'mode = "disable"' not in out
        assert "position" not in out
        assert "scale" not in out

    def test_monitor_empty_output_emits_empty_string(self) -> None:
        # The catch-all rule ``monitor = , preferred, auto, 1`` carries no
        # output name. Hyprland's Lua ``hl.monitor`` requires ``output`` as a
        # string ("output field is required and should be a string"), so the
        # empty name must surface as ``output = ""`` rather than be dropped.
        out = serialize_lua(parse_string("monitor = , preferred, auto, 1\n"))
        assert 'output = "",' in out
        assert 'mode = "preferred",' in out
        assert 'position = "auto",' in out
        assert "scale = 1," in out

    def test_monitor_empty_output_with_disable(self) -> None:
        # Empty output plus the disable short-form still emits ``output = ""``.
        out = serialize_lua(parse_string("monitor = , disable\n"))
        assert 'output = "",' in out
        assert "disabled = true," in out


class TestBezierKeyword:
    def test_bezier_emits_hl_curve(self) -> None:
        out = serialize_lua(parse_string("bezier = easeOut, 0.05, 0.9, 0.1, 1.0\n"))
        assert 'hl.curve("easeOut"' in out
        assert 'type = "bezier"' in out
        assert "{0.05, 0.9}" in out
        assert "{0.1, 1.0}" in out

    def test_bezier_with_integer_points(self) -> None:
        out = serialize_lua(parse_string("bezier = linear, 0, 0, 1, 1\n"))
        assert "{0, 0}" in out
        assert "{1, 1}" in out


class TestAnimationKeyword:
    def test_animation_full_form(self) -> None:
        out = serialize_lua(parse_string("animation = windows, 1, 7, easeOut, slide\n"))
        assert "hl.animation({" in out
        assert 'leaf = "windows",' in out
        assert "enabled = true," in out
        assert "speed = 7," in out
        assert 'bezier = "easeOut",' in out
        assert 'style = "slide",' in out

    def test_animation_disabled(self) -> None:
        out = serialize_lua(parse_string("animation = windows, 0, 7, default\n"))
        assert "enabled = false," in out

    def test_animation_synonyms_for_enabled(self) -> None:
        # Hyprlang accepts yes/on as truthy synonyms.
        out = serialize_lua(parse_string("animation = w, yes, 1, default\n"))
        assert "enabled = true," in out

    def test_animation_without_style(self) -> None:
        out = serialize_lua(parse_string("animation = layers, 1, 4, easeOut\n"))
        assert "style" not in out


class TestWindowRule:
    def test_v1_with_class_matcher(self) -> None:
        out = serialize_lua(parse_string("windowrule = float, class:^firefox$\n"))
        assert "hl.window_rule({" in out
        assert 'class = "^firefox$"' in out
        assert "float = true" in out

    def test_v1_bare_regex_treated_as_class(self) -> None:
        out = serialize_lua(parse_string("windowrule = float, ^firefox$\n"))
        assert 'class = "^firefox$"' in out

    def test_v2_multiple_matchers(self) -> None:
        out = serialize_lua(parse_string("windowrulev2 = float, class:^kitty$, title:^scratch$\n"))
        assert 'class = "^kitty$"' in out
        assert 'title = "^scratch$"' in out

    def test_valued_action(self) -> None:
        out = serialize_lua(parse_string("windowrulev2 = opacity 0.9, class:^kitty$\n"))
        assert "opacity = 0.9" in out


class TestLayerRule:
    def test_blur(self) -> None:
        out = serialize_lua(parse_string("layerrule = blur, ^waybar$\n"))
        assert "hl.layer_rule({" in out
        assert 'namespace = "^waybar$"' in out
        assert "blur = true" in out


class TestNamedRuleLuaEmission:
    """Block-form named rules round-trip through migration + Lua emission.

    ``normalize_rules`` collapses a block to a structured :class:`Rule`
    node and the Lua walker renders it as one
    ``hl.window_rule({...})`` / ``hl.layer_rule({...})`` call.
    """

    def test_named_window_block_emits_single_lua_call(self) -> None:
        out = serialize_lua(
            parse_string(
                "windowrule {\n"
                "    name = apply-something\n"
                "    match:class = my-window\n"
                "    border_size = 10\n"
                "    no_blur = on\n"
                "}\n"
            )
        )
        # One window_rule call carrying name + bundled effects.
        assert out.count("hl.window_rule(") == 1
        assert 'name = "apply-something"' in out
        assert 'class = "my-window"' in out
        assert "border_size = 10" in out
        assert "no_blur = true" in out

    def test_named_layer_block_emits_single_lua_call(self) -> None:
        out = serialize_lua(
            parse_string(
                "layerrule {\n"
                "    name = bundle\n"
                "    match:namespace = waybar\n"
                "    blur = on\n"
                "    ignore_alpha = 0.5\n"
                "}\n"
            )
        )
        assert out.count("hl.layer_rule(") == 1
        assert 'name = "bundle"' in out
        assert 'namespace = "waybar"' in out
        assert "blur = true" in out
        assert "ignore_alpha = 0.5" in out

    def test_section_key_form_also_emits_name(self) -> None:
        # ``windowrule[my-name] { … }`` carries the name in the section key.
        out = serialize_lua(
            parse_string("windowrule[from-key] {\n    match:class = kitty\n    float = on\n}\n")
        )
        assert 'name = "from-key"' in out
        assert "float = true" in out

    def test_disabled_block_emits_enabled_false(self) -> None:
        # Hyprland's Lua API spells the field ``enabled`` and rejects
        # ``enable`` outright — translate the Hyprlang ``enable = 0/1``
        # to Lua ``enabled = false/true`` on the way out.
        out = serialize_lua(
            parse_string(
                "windowrule {\n"
                "    name = off\n"
                "    enable = 0\n"
                "    match:class = X\n"
                "    float = on\n"
                "}\n"
            )
        )
        assert "enabled = false" in out
        assert "enable =" not in out  # never the bare ``enable`` field

    def test_rule_matcher_uses_var_reference(self) -> None:
        # A ``$var`` inside a v3 rule's matcher value must emit as the bare
        # ``var_NAME`` identifier, not the literal string ``"$NAME"`` (which
        # Hyprland's Lua loader rejects). The Rule path bypasses the keyword
        # emitter, so the rule walker has to expand ``$var`` itself.
        out = serialize_lua(
            parse_string("$myclass = kitty\nwindowrule = float, match:class $myclass\n")
        )
        assert 'local var_myclass = "kitty"' in out
        assert "class = var_myclass" in out
        assert "$myclass" not in out
        assert '"$myclass"' not in out

    def test_rule_effect_uses_var_reference(self) -> None:
        # Same expansion applies to effect arg values.
        out = serialize_lua(
            parse_string("$mywidth = 5\nwindowrule = bordersize $mywidth, match:class kitty\n")
        )
        assert "local var_mywidth = 5" in out or 'local var_mywidth = "5"' in out
        assert "bordersize = var_mywidth" in out
        assert "$mywidth" not in out


class TestWorkspaceRule:
    def test_basic(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, monitor:DP-1, default:true\n"))
        assert "hl.workspace_rule({" in out
        assert 'workspace = "1"' in out
        assert 'monitor = "DP-1"' in out
        assert "default = true" in out

    def test_named_workspace(self) -> None:
        out = serialize_lua(parse_string("workspace = special:magic, monitor:DP-1\n"))
        assert 'workspace = "special:magic"' in out


class TestGesture:
    def test_basic_gesture(self) -> None:
        out = serialize_lua(parse_string("gesture = 3, horizontal, workspace\n"))
        assert "hl.gesture({" in out
        assert "fingers = 3" in out
        assert 'direction = "horizontal"' in out
        assert 'action = "workspace"' in out

    def test_gesture_with_options(self) -> None:
        out = serialize_lua(parse_string("gesture = 4, vertical, special, workspace_name:magic\n"))
        assert 'workspace_name = "magic"' in out


class TestPermission:
    def test_basic_permission(self) -> None:
        out = serialize_lua(parse_string("permission = /usr/bin/grim, screencopy, allow\n"))
        assert 'hl.permission("/usr/bin/grim", "screencopy", "allow")' in out


class TestDeviceSection:
    def test_device_block(self) -> None:
        out = serialize_lua(
            parse_string("device {\n    name = epic-mouse-v1\n    sensitivity = -0.5\n}\n")
        )
        assert "hl.device({" in out
        assert 'name = "epic-mouse-v1"' in out
        assert "sensitivity = -0.5" in out
        # Device contents must NOT leak into hl.config({ device = … }).
        assert "hl.config(" not in out

    def test_two_device_blocks_each_get_their_own_call(self) -> None:
        out = serialize_lua(
            parse_string(
                "device {\n    name = mouse-1\n    sensitivity = -0.5\n}\n"
                "device {\n    name = mouse-2\n    sensitivity = 0.3\n}\n"
            )
        )
        assert out.count("hl.device({") == 2
        assert 'name = "mouse-1"' in out
        assert 'name = "mouse-2"' in out

    def test_non_device_section_still_goes_to_config(self) -> None:
        # `general { gaps_in = 5 }` is still merged into hl.config — only
        # `device { … }` is treated specially.
        out = serialize_lua(parse_string("general {\n    gaps_in = 5\n}\n"))
        assert "hl.config(" in out
        assert "hl.device" not in out


class TestModernWindowRule:
    """Hyprland 0.53+ ``windowrule = ACTION VALUE, match:KEY VALUE`` format."""

    def test_modern_match_prefix(self) -> None:
        out = serialize_lua(parse_string("windowrule = stay_focused on, match:title ^Albert$\n"))
        assert "stay_focused = true" in out
        assert 'title = "^Albert$"' in out
        # The literal `match:title …` must not leak into the matcher dict.
        assert 'class = "match:title' not in out
        assert '["stay_focused on"]' not in out

    def test_modern_multiple_matchers(self) -> None:
        line = (
            "windowrule = no_focus on, match:class ^jetbrains-.*$, "
            "match:title ^win.*$, match:float 1\n"
        )
        out = serialize_lua(parse_string(line))
        assert "no_focus = true" in out
        assert 'class = "^jetbrains-.*$"' in out
        assert 'title = "^win.*$"' in out
        assert "float = 1" in out

    def test_action_value_off(self) -> None:
        out = serialize_lua(parse_string("windowrule = float off, match:class Firefox\n"))
        assert "float = false" in out

    def test_string_value_action(self) -> None:
        out = serialize_lua(
            parse_string("windowrule = suppress_event maximize, match:initial_title ^Godot$\n")
        )
        assert 'suppress_event = "maximize"' in out

    def test_valued_action(self) -> None:
        out = serialize_lua(parse_string("windowrule = opacity 0.9, match:class ^kitty$\n"))
        assert "opacity = 0.9" in out

    def test_match_first_order_normalises_to_same_output(self) -> None:
        # hyprmod writes windowrules in ``match:..., effect ...`` order while
        # the Hyprland wiki examples often use ``effect, match:...``. Both
        # must parse to identical Lua.
        effect_first = serialize_lua(
            parse_string("windowrule = stay_focused on, match:title ^Albert$\n")
        )
        match_first = serialize_lua(
            parse_string("windowrule = match:title ^Albert$, stay_focused on\n")
        )
        assert effect_first == match_first

    def test_layerrule_match_first_order(self) -> None:
        # The format hyprmod's layer_rules module emits.
        out = serialize_lua(parse_string("layerrule = match:namespace ^waybar$, blur on\n"))
        assert 'namespace = "^waybar$"' in out
        assert "blur = true" in out

    def test_every_effect_survives(self) -> None:
        # One v3 line can carry several effects. Only the first used to
        # reach the Lua table; the rest were dropped without a word.
        out = serialize_lua(
            parse_string(
                "windowrule = match:class ^(kitty)$, float on, opacity 0.8, size 800 600\n"
            )
        )
        assert "float = true" in out
        assert "opacity = 0.8" in out
        assert 'size = "800 600"' in out

    def test_every_layerrule_effect_survives(self) -> None:
        out = serialize_lua(
            parse_string("layerrule = match:namespace ^(waybar)$, blur on, ignore_alpha 0.5\n")
        )
        assert "blur = true" in out
        assert "ignore_alpha = 0.5" in out

    def test_effects_keep_their_authored_order(self) -> None:
        out = serialize_lua(
            parse_string("windowrule = match:class ^(kitty)$, rounding 8, float on, opacity 0.8\n")
        )
        assert out.index("rounding = 8") < out.index("float = true") < out.index("opacity = 0.8")

    def test_effectless_rule_goes_to_manual_conversion(self) -> None:
        # Hyprland rejects a rule with nothing to apply. Emitting Lua for it
        # would be a no-op the user never finds out about, so the line lands
        # in the trailing manual-conversion block instead.
        out = serialize_lua(parse_string("windowrule = match:class ^(kitty)$\n"))
        assert "hl.window_rule" not in out
        assert "windowrule = match:class ^(kitty)$" in out


class TestRuleLiveApplyMatchesTheFile:
    """``keyword_to_lua`` and the document walker have to agree on a rule.

    They are the two ways a rule reaches Hyprland: pushed live through
    ``hyprctl eval``, or written to the config. When they disagree, an
    editor applies one thing now and saves a different one for later.
    """

    RULES = [
        "match:class ^(kitty)$, float on",
        "match:class ^(kitty)$, float on, opacity 0.8, size 800 600",
        "match:class ^(kitty)$, match:title ^(scratch)$, no_blur on, rounding 8",
        "stay_focused on, match:title ^Albert$",
    ]

    @pytest.mark.parametrize("body", RULES)
    def test_live_snippet_matches_the_written_rule(self, body: str) -> None:
        doc = parse_string(f"windowrule = {body}\n")
        normalize_rules(doc)
        written = [render_rule_lua(line) for line in doc.lines if isinstance(line, Rule)]
        assert keyword_to_lua("windowrule", body) == written[0]

    def test_live_push_carries_every_effect(self) -> None:
        snippet = keyword_to_lua("windowrule", "match:class ^(kitty)$, float on, opacity 0.8")
        assert "float = true" in snippet
        assert "opacity = 0.8" in snippet

    def test_effectless_rule_raises_instead_of_emitting_a_comment(self) -> None:
        # A Lua comment evaluates fine, so the caller would report success
        # for a rule the compositor never received.
        with pytest.raises(ValueError, match="keyword 'windowrule'"):
            keyword_to_lua("windowrule", "match:class ^(kitty)$")


class TestBlockRuleSyntax:
    """Hyprland 0.54+ accepts ``windowrule { … }`` / ``layerrule { … }`` blocks.

    Each block defines one rule; the assignments inside become its fields,
    and ``match:KEY = VALUE`` lines populate the ``match`` table.
    """

    def test_windowrule_block_basic(self) -> None:
        config = (
            "windowrule {\n"
            "    match:class = ^(thunar)$\n"
            "    match:title = ^(File Operation Progress)$\n"
            "    float = on\n"
            "    center = on\n"
            "    size = (monitor_w*0.26) (monitor_h*0.18)\n"
            "}\n"
        )
        out = serialize_lua(parse_string(config))
        assert "hl.window_rule({" in out
        # Must NOT have leaked into hl.config({ windowrule = … }).
        assert "windowrule = {" not in out
        assert 'class = "^(thunar)$"' in out
        assert 'title = "^(File Operation Progress)$"' in out
        assert "float = true" in out
        assert "center = true" in out
        assert 'size = "(monitor_w*0.26) (monitor_h*0.18)"' in out

    def test_windowrule_block_with_name_field(self) -> None:
        config = (
            "windowrule {\n"
            "    name = Thunar-Progress\n"
            "    match:class = ^(thunar)$\n"
            "    float = on\n"
            "}\n"
        )
        out = serialize_lua(parse_string(config))
        assert 'name = "Thunar-Progress"' in out

    def test_layerrule_block(self) -> None:
        config = (
            "layerrule {\n"
            "    match:namespace = ^(waybar)$\n"
            "    blur = on\n"
            "    ignore_alpha = 0.5\n"
            "}\n"
        )
        out = serialize_lua(parse_string(config))
        assert "hl.layer_rule({" in out
        assert 'namespace = "^(waybar)$"' in out
        assert "blur = true" in out
        assert "ignore_alpha = 0.5" in out

    def test_two_blocks_each_emit_one_call(self) -> None:
        config = (
            "windowrule {\n"
            "    match:class = ^kitty$\n"
            "    float = on\n"
            "}\n"
            "windowrule {\n"
            "    match:class = ^firefox$\n"
            "    pin = on\n"
            "}\n"
        )
        out = serialize_lua(parse_string(config))
        assert out.count("hl.window_rule({") == 2

    def test_windowrule_nested_match_block(self) -> None:
        # Hyprland 0.53+ also allows the matchers to live in a nested
        # ``match { … }`` sub-block rather than flat ``match:KEY`` lines.
        # The sub-block fields must nest under the rule's ``match`` table,
        # not leak into ``hl.config({ windowrule = { match = … } })`` (which
        # Hyprland rejects with "unknown config key windowrule.match.*").
        config = (
            "windowrule {\n"
            "    name = fix-xwayland-drags\n"
            "    no_focus = true\n"
            "    match {\n"
            "        class = ^$\n"
            "        xwayland = true\n"
            "        float = true\n"
            "    }\n"
            "}\n"
        )
        out = serialize_lua(parse_string(config))
        assert out.count("hl.window_rule({") == 1
        assert "windowrule = {" not in out  # never leaks into hl.config
        assert "match = {" in out
        assert 'name = "fix-xwayland-drags"' in out
        assert "no_focus = true" in out
        assert 'class = "^$"' in out
        assert "xwayland = true" in out
        assert "float = true" in out

    def test_layerrule_nested_match_block(self) -> None:
        config = (
            "layerrule {\n"
            "    name = noctalia\n"
            "    blur = true\n"
            "    match {\n"
            "        namespace = noctalia-background-.*$\n"
            "    }\n"
            "}\n"
        )
        out = serialize_lua(parse_string(config))
        assert out.count("hl.layer_rule({") == 1
        assert "layerrule = {" not in out
        assert 'namespace = "noctalia-background-.*$"' in out
        assert "blur = true" in out

    def test_nested_match_effect_and_matcher_dont_collide(self) -> None:
        # ``float`` is both an effect (make matched window float) and a
        # matcher (match floating windows). The effect stays top-level while
        # the matcher nests under ``match`` — they must not overwrite.
        config = (
            "windowrule {\n"
            "    float = yes\n"
            "    match {\n"
            "        float = false\n"
            "        class = hyprland-run\n"
            "    }\n"
            "}\n"
        )
        out = serialize_lua(parse_string(config))
        assert "float = true" in out  # the effect
        assert "float = false" in out  # the matcher, nested under match
        assert 'class = "hyprland-run"' in out

    def test_multiple_nested_match_blocks_keep_own_matchers(self) -> None:
        # Regression: every windowrule block writes the same
        # ``windowrule:match:*`` path, so the buggy walker collapsed all of
        # their matchers into one shared (and invalid) hl.config entry.
        config = (
            "windowrule {\n"
            "    suppress_event = maximize\n"
            "    match { class = .* }\n"
            "}\n"
            "windowrule {\n"
            "    no_focus = true\n"
            "    match { class = ^$ }\n"
            "}\n"
        )
        out = serialize_lua(parse_string(config))
        assert out.count("hl.window_rule({") == 2
        assert "windowrule = {" not in out
        assert 'class = ".*"' in out
        assert 'class = "^$"' in out

    def test_submap_block_wraps_binds_in_define_submap(self) -> None:
        # Hyprlang's submap declaration is a directive — the binds between
        # ``submap = NAME`` and ``submap = reset`` belong to that named map.
        # Without the walker recognising this, those binds would leak to the
        # global keymap (real bug surfaced by the vitorf7 dotfiles).
        config = (
            "bind = SUPER, R, submap, resize\n"
            "submap = resize\n"
            "bind = , right, resizeactive, 10 0\n"
            "bind = , Escape, submap, reset\n"
            "submap = reset\n"
            "bind = SUPER, Q, killactive\n"
        )
        out = serialize_lua(parse_string(config))
        assert 'hl.define_submap("resize", function()' in out
        assert "end)" in out
        # The submap-entry bind sits before define_submap, the unbound
        # ``killactive`` sits after — both at global scope.
        entry_idx = out.index('hl.bind("SUPER + R"')
        define_idx = out.index("hl.define_submap")
        global_idx = out.index('hl.bind("SUPER + Q"')
        assert entry_idx < define_idx < global_idx
        # No raw `submap = …` lines leaked to the TODO block.
        assert "submap = resize" not in out
        assert "submap = reset" not in out

    def test_empty_submap_is_dropped(self) -> None:
        # Hyprland rejects submaps with no binds. Emitting an empty
        # ``hl.define_submap`` would just be noise.
        config = "submap = resize\nsubmap = reset\n"
        out = serialize_lua(parse_string(config))
        assert "hl.define_submap" not in out

    def test_unclosed_submap_still_emits(self) -> None:
        # Truncated configs (in-progress edits) can end mid-submap. Without
        # draining the open scope at assembly time, the body binds would
        # silently vanish from the output.
        config = "submap = resize\nbind = , right, resizeactive, 10 0\n"
        out = serialize_lua(parse_string(config))
        assert 'hl.define_submap("resize"' in out
        assert "hl.dsp.window.resize" in out

    def test_windowrule_block_with_workspace_action(self) -> None:
        # ``workspace`` is also a top-level Hyprland keyword (``workspace = 1,
        # monitor:DP-1``), so the walker has to recognize it as a rule field
        # when it appears inside a ``windowrule { … }`` block — otherwise it
        # leaks out as a separate ``hl.workspace_rule(...)`` call and the
        # original window rule loses its assignment action.
        config = (
            "windowrule {\n"
            "    name = ghostty-in-ws-1\n"
            "    match:class = ghostty\n"
            "    workspace = 1\n"
            "}\n"
        )
        out = serialize_lua(parse_string(config))
        assert out.count("hl.window_rule({") == 1
        assert "hl.workspace_rule" not in out
        assert "workspace = 1," in out


class TestExecBlocks:
    def test_exec_emits_at_top_level(self) -> None:
        # ``exec`` runs on every reload (Hyprland re-evaluates the Lua
        # file), so each translates to a bare top-level call instead of
        # nesting in an ``hl.on("hyprland.start", …)`` block whose
        # callback would only fire at session startup.
        out = serialize_lua(parse_string("exec = waybar\nexec = nm-applet\n"))
        assert 'hl.on("hyprland.start"' not in out
        assert 'hl.exec_cmd("waybar")' in out
        assert 'hl.exec_cmd("nm-applet")' in out

    def test_exec_once_batched_in_start_block(self) -> None:
        # ``exec-once`` fires only at session startup; the ``hl.on``
        # callback gives that semantics. Multiple entries in the same
        # group share one block.
        out = serialize_lua(parse_string("exec-once = waybar\nexec-once = nm-applet\n"))
        assert 'hl.on("hyprland.start", function()' in out
        assert 'hl.exec_cmd("waybar")' in out
        assert 'hl.exec_cmd("nm-applet")' in out
        # Only one start block, not two.
        assert out.count('hl.on("hyprland.start"') == 1

    def test_no_migration_markers_in_exec_blocks(self) -> None:
        # The emitter keeps ``exec`` and ``exec-once`` distinct, so it never
        # needs the historical ``-- TODO: was exec-once`` hint.
        out = serialize_lua(parse_string("exec-once = dunst\n"))
        assert "TODO: was exec-once" not in out
        assert 'hl.exec_cmd("dunst")' in out

    def test_exec_shutdown_separate_block(self) -> None:
        out = serialize_lua(parse_string("exec-shutdown = sync\n"))
        assert 'hl.on("hyprland.shutdown", function()' in out
        assert 'hl.exec_cmd("sync")' in out

    def test_uses_top_level_exec_cmd_not_dispatcher(self) -> None:
        # hl.dsp.exec_cmd returns a dispatcher object that can't be called
        # directly; the imperative version is hl.exec_cmd.
        out = serialize_lua(parse_string("exec = waybar\n"))
        assert "hl.exec_cmd" in out
        assert "hl.dsp.exec_cmd" not in out
