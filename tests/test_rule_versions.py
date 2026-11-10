"""Version-aware windowrule / layerrule serialization.

Hyprland adopted the v3 ``match:`` grammar for windowrules in 0.53 and
for layerrules in 0.54. Below those boundaries the serializer must emit
the effect-first form the older compositor understands; at/above (and
when the version is unknown) it emits v3.
"""

from hyprland_config import (
    Rule,
    render_rule_hyprlang,
    render_rule_live,
    render_rule_lua,
)
from hyprland_config._core._rules import (
    V2_TO_V3_EFFECT,
    V2_TO_V3_MATCHER,
    V3_TO_V2_EFFECT,
    V3_TO_V2_MATCHER,
)


def _window(matchers, effects, **kw):
    return Rule(raw="", kind="windowrule", matchers=matchers, effects=effects, **kw)


def _layer(namespace, effects, **kw):
    return Rule(
        raw="", kind="layerrule", matchers=[("namespace", namespace)], effects=effects, **kw
    )


class TestWindowRuleVersions:
    def test_issue_41_rule_on_pre_v3_emits_windowrulev2(self):
        """The reported case: a float rule on Hyprland 0.49 must be v2.

        v3 ``windowrule = match:class …`` is rejected by 0.49's parser
        ("Invalid rulev2 found"); 0.49 only understands ``windowrulev2``.
        """
        rule = _window([("class", r"^(io\.github\.bluemancz\.hyprmod)$")], [("float", "")])
        assert (
            render_rule_hyprlang(rule, "0.49.0")
            == r"windowrulev2 = float, class:^(io\.github\.bluemancz\.hyprmod)$" + "\n"
        )

    def test_same_rule_on_v3_unchanged(self):
        rule = _window([("class", "kitty")], [("float", "")])
        assert render_rule_hyprlang(rule, "0.55.2") == "windowrule = match:class kitty, float on\n"

    def test_unknown_version_defaults_to_v3(self):
        rule = _window([("class", "kitty")], [("float", "")])
        assert render_rule_hyprlang(rule) == "windowrule = match:class kitty, float on\n"

    def test_053_is_v3(self):
        """0.53 is the exact boundary — v3 from here up."""
        rule = _window([("class", "kitty")], [("float", "")])
        assert render_rule_hyprlang(rule, "0.53.0").startswith("windowrule = match:")

    def test_052_is_pre_v3(self):
        rule = _window([("class", "kitty")], [("float", "")])
        assert render_rule_hyprlang(rule, "0.52.0").startswith("windowrulev2 = ")

    def test_pre_v3_renames_effect_and_matcher(self):
        """Effect/matcher words revert to their pre-v3 spellings."""
        rule = _window([("initial_class", "kitty")], [("no_blur", "")])
        assert render_rule_hyprlang(rule, "0.49.0") == "windowrulev2 = noblur, initialClass:kitty\n"

    def test_pre_v3_negation_uses_tilde(self):
        rule = _window([("class", "negative:firefox")], [("float", "")])
        assert render_rule_hyprlang(rule, "0.49.0") == "windowrulev2 = float, ~class:firefox\n"

    def test_pre_v3_effect_with_args_keeps_args(self):
        rule = _window([("class", "kitty")], [("opacity", "0.8 0.95")])
        assert (
            render_rule_hyprlang(rule, "0.49.0") == "windowrulev2 = opacity 0.8 0.95, class:kitty\n"
        )

    def test_pre_v3_multi_effect_splits_into_lines(self):
        """Pre-v3 has no multi-effect line; each effect repeats the matchers."""
        rule = _window([("class", "kitty")], [("float", ""), ("no_blur", "")])
        assert render_rule_hyprlang(rule, "0.49.0") == (
            "windowrulev2 = float, class:kitty\nwindowrulev2 = noblur, class:kitty\n"
        )

    def test_pre_v3_named_rule_drops_name_with_comment(self):
        rule = _window([("class", "kitty")], [("opacity", "0.7")], name="dim")
        out = render_rule_hyprlang(rule, "0.49.0")
        assert "# name 'dim' dropped" in out
        assert "windowrulev2 = opacity 0.7, class:kitty" in out

    def test_pre_v3_disabled_rule_comments_out_lines(self):
        rule = _window([("class", "kitty")], [("float", "")], enabled=False)
        out = render_rule_hyprlang(rule, "0.49.0")
        assert "# windowrulev2 = float, class:kitty" in out
        # no uncommented rule line leaks through
        assert not any(line.startswith("windowrulev2") for line in out.splitlines())


class TestLayerRuleVersions:
    def test_pre_v3_layer_uses_effect_first_bare_namespace(self):
        rule = _layer(r"^(waybar)$", [("blur", "")])
        assert render_rule_hyprlang(rule, "0.49.0") == r"layerrule = blur, ^(waybar)$" + "\n"

    def test_v3_layer_uses_match_namespace(self):
        rule = _layer(r"^(waybar)$", [("blur", "")])
        expected = r"layerrule = match:namespace ^(waybar)$, blur on" + "\n"
        assert render_rule_hyprlang(rule, "0.55.2") == expected

    def test_layer_boundary_is_054_not_053(self):
        """Layer rules kept the effect-first form through 0.53."""
        rule = _layer("rofi", [("blur", "")])
        assert render_rule_hyprlang(rule, "0.53.0") == "layerrule = blur, rofi\n"
        assert render_rule_hyprlang(rule, "0.54.0").startswith("layerrule = match:namespace")

    def test_pre_v3_layer_renames_effects(self):
        rule = _layer("rofi", [("no_anim", "")])
        assert render_rule_hyprlang(rule, "0.53.0") == "layerrule = noanim, rofi\n"

    def test_pre_v3_layer_keeps_numeric_arg(self):
        rule = _layer("rofi", [("ignore_alpha", "0.5")])
        assert render_rule_hyprlang(rule, "0.53.0") == "layerrule = ignorealpha 0.5, rofi\n"


class TestRenderRuleLive:
    def test_live_pre_v3_window_pair(self):
        rule = _window([("class", "kitty")], [("float", "")])
        assert render_rule_live(rule, "0.49.0") == [("windowrulev2", "float, class:kitty")]

    def test_live_v3_window_pair(self):
        rule = _window([("class", "kitty")], [("float", "")])
        assert render_rule_live(rule, "0.55.2") == [("windowrule", "match:class kitty, float on")]

    def test_live_pre_v3_multi_effect_yields_one_pair_per_effect(self):
        rule = _window([("class", "kitty")], [("float", ""), ("no_blur", "")])
        assert render_rule_live(rule, "0.49.0") == [
            ("windowrulev2", "float, class:kitty"),
            ("windowrulev2", "noblur, class:kitty"),
        ]

    def test_live_v3_multi_effect_stays_one_pair(self):
        rule = _window([("class", "kitty")], [("float", ""), ("no_blur", "")])
        assert render_rule_live(rule, "0.55.2") == [
            ("windowrule", "match:class kitty, float on, no_blur on")
        ]

    def test_live_layer_pre_v3(self):
        rule = _layer("waybar", [("blur", "")])
        assert render_rule_live(rule, "0.49.0") == [("layerrule", "blur, waybar")]


class TestHyprland057BoolEffects:
    """0.57 added boolean window-rule effects; both emitters must fill a value."""

    def test_hyprlang_fills_on(self):
        for effect in ("no_glow", "no_wobble", "no_xdg_drags", "no_auto_hdr", "confine_pointer"):
            rule = _window([("class", "kitty")], [(effect, "")])
            assert render_rule_hyprlang(rule) == f"windowrule = match:class kitty, {effect} on\n"

    def test_lua_emits_true(self):
        for effect in ("no_glow", "no_wobble", "no_xdg_drags", "no_auto_hdr", "confine_pointer"):
            rule = _window([("class", "kitty")], [(effect, "")])
            assert f"{effect} = true" in render_rule_lua(rule)


class TestRenameMapConsistency:
    """The pre-v3 emitter inverts the v2→v3 migration maps; guard the round-trip."""

    def test_effect_maps_are_inverses(self):
        assert V3_TO_V2_EFFECT == {v: k for k, v in V2_TO_V3_EFFECT.items()}
        assert len(V3_TO_V2_EFFECT) == len(V2_TO_V3_EFFECT)

    def test_matcher_maps_are_inverses(self):
        assert V3_TO_V2_MATCHER == {v: k for k, v in V2_TO_V3_MATCHER.items()}
        assert len(V3_TO_V2_MATCHER) == len(V2_TO_V3_MATCHER)
