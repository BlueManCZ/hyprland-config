"""Tests for bind parsing and data model."""

from hyprland_config import (
    BindData,
    parse_bind_line,
)


class TestParseBind:
    def test_basic_bind(self):
        bd = parse_bind_line("bind = SUPER, Q, killactive,")
        assert bd is not None
        assert bd.bind_type == "bind"
        assert bd.description == ""
        assert bd.mods == ["SUPER"]
        assert bd.key == "Q"
        assert bd.dispatcher == "killactive"

    def test_bind_with_arg(self):
        bd = parse_bind_line("bind = SUPER, Return, exec, kitty")
        assert bd is not None
        assert bd.dispatcher == "exec"
        assert bd.arg == "kitty"

    def test_binde_type(self):
        bd = parse_bind_line("binde = SUPER, L, resizeactive, 10 0")
        assert bd is not None
        assert bd.bind_type == "binde"

    def test_malformed_returns_none(self):
        assert parse_bind_line("not a bind") is None
        assert parse_bind_line("bind = SUPER") is None

    def test_no_mods(self):
        bd = parse_bind_line("bind = , Print, exec, screenshot")
        assert bd is not None
        assert bd.mods == []
        assert bd.key == "Print"

    def test_trailing_comma_in_arg_stripped(self):
        # `bind = SUPER, J, layoutmsg, togglesplit,` is real-world Hyprlang —
        # users put a trailing comma for visual symmetry or as an artefact of
        # an earlier inline comment. The trailing empty field used to glue
        # itself onto the dispatcher arg as `"togglesplit,"`.
        bd = parse_bind_line("bind = SUPER, J, layoutmsg, togglesplit,")
        assert bd is not None
        assert bd.dispatcher == "layoutmsg"
        assert bd.arg == "togglesplit"

    def test_bindd_separates_description_from_dispatcher(self):
        bd = parse_bind_line("bindd = SUPER, B, Browser, exec, omarchy-launch-browser")

        assert bd is not None
        assert bd.description == "Browser"
        assert bd.dispatcher == "exec"
        assert bd.arg == "omarchy-launch-browser"
        assert bd.to_line() == "bindd = SUPER, B, Browser, exec, omarchy-launch-browser"

    def test_combined_description_flag_is_supported(self):
        bd = parse_bind_line("binded = SUPER SHIFT, left, Resize left, resizeactive, -50 0")

        assert bd is not None
        assert bd.bind_type == "binded"
        assert bd.description == "Resize left"
        assert bd.dispatcher == "resizeactive"
        assert bd.arg == "-50 0"


class TestBindData:
    def test_to_line(self):
        bd = BindData(mods=["SUPER"], key="Q", dispatcher="killactive", arg="")
        assert bd.to_line() == "bind = SUPER, Q, killactive"

    def test_to_line_with_arg(self):
        bd = BindData(mods=["SUPER"], key="Return", dispatcher="exec", arg="kitty")
        assert bd.to_line() == "bind = SUPER, Return, exec, kitty"

    def test_to_line_bindm_no_trailing_comma(self):
        """Hyprland's ``bindm`` rejects a trailing comma with 'bind: too many args'."""
        bd = BindData(
            bind_type="bindm",
            mods=["SUPER"],
            key="mouse:272",
            dispatcher="movewindow",
            arg="",
        )
        assert bd.to_line() == "bindm = SUPER, mouse:272, movewindow"

    def test_to_line_preserves_bind_description(self):
        bd = BindData(
            bind_type="bindd",
            mods=["SUPER"],
            key="B",
            description="Browser",
            dispatcher="exec",
            arg="omarchy-launch-browser",
        )

        assert bd.to_line() == "bindd = SUPER, B, Browser, exec, omarchy-launch-browser"

    def test_to_line_requires_bind_prefix_for_description_flag(self):
        bd = BindData(
            bind_type="customd",
            mods=["SUPER"],
            key="B",
            description="Browser",
            dispatcher="exec",
            arg="firefox",
        )

        assert bd.to_line() == "customd = SUPER, B, exec, firefox"

    def test_combo_normalized(self):
        bd1 = BindData(mods=["SUPER", "SHIFT"], key="q")
        bd2 = BindData(mods=["SHIFT", "SUPER"], key="Q")
        assert bd1.combo == bd2.combo

    def test_format_shortcut(self):
        bd = BindData(mods=["SUPER", "SHIFT"], key="a")
        assert bd.format_shortcut() == "SUPER + SHIFT + A"

    def test_format_action_with_arg(self):
        bd = BindData(dispatcher="exec", arg="firefox")
        assert bd.format_action() == "exec: firefox"

    def test_format_action_no_arg(self):
        bd = BindData(dispatcher="killactive")
        assert bd.format_action() == "killactive"

    def test_roundtrip(self):
        line = "bind = SUPER SHIFT, A, exec, firefox --no-remote"
        bd = parse_bind_line(line)
        assert bd is not None
        rebuilt = bd.to_line()
        bd2 = parse_bind_line(rebuilt)
        assert bd2 is not None
        assert bd.combo == bd2.combo
        assert bd.dispatcher == bd2.dispatcher
