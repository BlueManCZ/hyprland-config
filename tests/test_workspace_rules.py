"""Bidirectional workspace-rule field translation.

Workspace rules use snake_case field names in Lua and a mix of run-
together names / inverted booleans in Hyprlang (e.g. Lua ``no_border``
↔ Hyprlang ``border``). Each test asserts the same logical rule round-
trips identically through both formats so a user editing in one form
and re-reading from the other never sees their settings drift.
"""

import functools
import shutil
from pathlib import Path

import pytest

from hyprland_config import (
    load_lua,
    parse_string,
    serialize_any,
    serialize_hyprlang,
    serialize_lua,
)
from hyprland_config._lua._workspace_rules import (
    format_layout_opts,
    hyprlang_field_to_lua,
    lua_field_to_hyprlang,
    parse_layoutopt,
)


@functools.cache
def _lua_available() -> bool:
    return any(shutil.which(name) is not None for name in ("lua", "lua5.4", "lua5.3"))


requires_lua = pytest.mark.skipif(not _lua_available(), reason="no lua interpreter on PATH")


def _hyprlang_to_lua(text: str) -> str:
    """Round-trip a Hyprlang workspace block through the Lua emitter."""
    doc = parse_string(text, lenient=True)
    return serialize_any(doc, Path("/tmp/probe.lua"))


def _lua_to_hyprlang(tmp_path: Path, code: str) -> str:
    """Round-trip a Lua workspace block through the Hyprlang serializer."""
    path = tmp_path / "ws.lua"
    path.write_text(code)
    doc = load_lua(path)
    return serialize_hyprlang(doc)


# ---------------------------------------------------------------------------
# Field-name translation — Hyprlang → Lua (emit path)
# ---------------------------------------------------------------------------


class TestEmitWorkspaceFields:
    """Hyprlang ``workspace = ...`` lines render correct Lua field names."""

    def test_gapsin_to_gaps_in(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, gapsin:5\n"))
        assert "gaps_in = 5" in out
        assert "gapsin" not in out

    def test_gapsout_to_gaps_out(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, gapsout:10\n"))
        assert "gaps_out = 10" in out
        assert "gapsout" not in out

    def test_bordersize_to_border_size(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, bordersize:3\n"))
        assert "border_size = 3" in out
        assert "bordersize" not in out

    def test_default_name_camelcase_to_snake(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, defaultName:work\n"))
        assert 'default_name = "work"' in out
        assert "defaultName" not in out

    def test_on_created_empty_hyphens_to_underscores(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, on-created-empty:kitty\n"))
        assert 'on_created_empty = "kitty"' in out
        assert "on-created-empty" not in out

    def test_persistent_passthrough(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, persistent:true\n"))
        assert "persistent = true" in out

    def test_default_passthrough(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, default:true\n"))
        assert "default = true" in out

    def test_decorate_passthrough(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, decorate:false\n"))
        assert "decorate = false" in out

    def test_unknown_field_passthrough(self) -> None:
        # Plugin / future-Hyprland fields keep their original name + value;
        # Lua's hl.workspace_rule will reject them at runtime, but at least
        # the user can see what they wrote.
        out = serialize_lua(parse_string("workspace = 1, plugin_field:42\n"))
        assert "plugin_field = 42" in out


class TestEmitWorkspaceLayoutOpts:
    """Hyprlang ``layoutopt:key:value`` becomes a nested ``layout_opts`` table."""

    def test_single_layoutopt_becomes_nested_table(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, layoutopt:direction:right\n"))
        assert "layout_opts = {" in out
        assert 'direction = "right"' in out
        # The flat pass-through form must not appear.
        assert 'layoutopt = "direction:right"' not in out

    def test_multiple_layoutopts_collect_into_one_table(self) -> None:
        out = serialize_lua(
            parse_string("workspace = 1, layoutopt:direction:right, layoutopt:foo:5\n")
        )
        assert 'direction = "right"' in out
        assert "foo = 5" in out
        # Only one layout_opts table, not two.
        assert out.count("layout_opts") == 1

    def test_layout_field_stays_flat_string(self) -> None:
        # ``layout`` (not ``layoutopt``) is a plain string field, untouched.
        out = serialize_lua(parse_string("workspace = 1, layout:scrolling\n"))
        assert 'layout = "scrolling"' in out


class TestEmitWorkspaceBoolInversion:
    """Hyprlang ``border``/``rounding``/``shadow`` flip sense to Lua ``no_*``."""

    def test_border_false_becomes_no_border_true(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, border:false\n"))
        assert "no_border = true" in out
        assert " border = " not in out  # no positive form

    def test_border_true_becomes_no_border_false(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, border:true\n"))
        assert "no_border = false" in out

    def test_rounding_false_becomes_no_rounding_true(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, rounding:false\n"))
        assert "no_rounding = true" in out

    def test_shadow_true_becomes_no_shadow_false(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, shadow:true\n"))
        assert "no_shadow = false" in out


class TestEmitWorkspaceGaps:
    """Multi-value Hyprlang gaps expand to 4-key Lua tables."""

    def test_scalar_gap_stays_scalar(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, gapsin:5\n"))
        assert "gaps_in = 5" in out
        # Confirm no spurious table is emitted.
        assert "{" not in out.split("gaps_in")[1].split("\n")[0]

    def test_four_value_gap_expands_to_table(self) -> None:
        out = serialize_lua(parse_string("workspace = 1, gapsout:5 10 15 20\n"))
        assert "top = 5," in out
        assert "right = 10," in out
        assert "bottom = 15," in out
        assert "left = 20," in out

    def test_two_value_gap_expands_via_css_shorthand(self) -> None:
        # ``5 10`` → vertical=5, horizontal=10 (CSS shorthand).
        out = serialize_lua(parse_string("workspace = 1, gapsin:5 10\n"))
        assert "top = 5," in out
        assert "right = 10," in out
        assert "bottom = 5," in out
        assert "left = 10," in out

    def test_three_value_gap_expands_via_css_shorthand(self) -> None:
        # ``5 10 15`` → top=5, horizontal=10, bottom=15.
        out = serialize_lua(parse_string("workspace = 1, gapsin:5 10 15\n"))
        assert "top = 5," in out
        assert "right = 10," in out
        assert "bottom = 15," in out
        assert "left = 10," in out


# ---------------------------------------------------------------------------
# Field-name translation — Lua → Hyprlang (read path)
# ---------------------------------------------------------------------------


@requires_lua
class TestReadWorkspaceFields:
    """``hl.workspace_rule({…})`` calls deserialise to correct Hyprlang tokens."""

    def test_gaps_in_to_gapsin(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(tmp_path, "hl.workspace_rule({workspace = 1, gaps_in = 5})")
        assert "gapsin:5" in out
        assert "gaps_in" not in out

    def test_gaps_out_to_gapsout(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(tmp_path, "hl.workspace_rule({workspace = 1, gaps_out = 10})")
        assert "gapsout:10" in out
        assert "gaps_out" not in out

    def test_border_size_to_bordersize(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(tmp_path, "hl.workspace_rule({workspace = 1, border_size = 3})")
        assert "bordersize:3" in out

    def test_default_name_to_camelcase(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(
            tmp_path, "hl.workspace_rule({workspace = 1, default_name = 'work'})"
        )
        assert "defaultName:work" in out

    def test_on_created_empty_underscores_to_hyphens(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(
            tmp_path, "hl.workspace_rule({workspace = 1, on_created_empty = 'kitty'})"
        )
        assert "on-created-empty:kitty" in out

    def test_unknown_field_passthrough(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(
            tmp_path, "hl.workspace_rule({workspace = 1, plugin_field = 'value'})"
        )
        assert "plugin_field:value" in out


@requires_lua
class TestReadWorkspaceLayoutOpts:
    """Lua ``layout_opts`` tables fan back out to ``layoutopt:key:value`` tokens."""

    def test_single_option(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(
            tmp_path,
            "hl.workspace_rule({workspace = 1, layout_opts = {direction = 'right'}})",
        )
        assert "layoutopt:direction:right" in out
        assert "layout_opts" not in out

    def test_multiple_options_each_get_a_token(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(
            tmp_path,
            "hl.workspace_rule({workspace = 1, layout_opts = {direction = 'right', foo = 5}})",
        )
        assert "layoutopt:direction:right" in out
        assert "layoutopt:foo:5" in out


@requires_lua
class TestReadWorkspaceBoolInversion:
    """Lua ``no_*`` fields flip to positive Hyprlang sense."""

    def test_no_border_true_becomes_border_false(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(tmp_path, "hl.workspace_rule({workspace = 1, no_border = true})")
        assert "border:false" in out
        assert "no_border" not in out

    def test_no_rounding_true_becomes_rounding_false(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(tmp_path, "hl.workspace_rule({workspace = 1, no_rounding = true})")
        assert "rounding:false" in out

    def test_no_shadow_false_becomes_shadow_true(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(tmp_path, "hl.workspace_rule({workspace = 1, no_shadow = false})")
        assert "shadow:true" in out


@requires_lua
class TestReadWorkspaceGaps:
    """Lua gap tables collapse to space-separated Hyprlang values."""

    def test_scalar_int(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(tmp_path, "hl.workspace_rule({workspace = 1, gaps_in = 5})")
        assert "gapsin:5" in out

    def test_full_four_side_table(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(
            tmp_path,
            "hl.workspace_rule({workspace = 1, gaps_out = {top = 5, right = 10, "
            "bottom = 15, left = 20}})",
        )
        assert "gapsout:5 10 15 20" in out

    def test_partial_table_defaults_missing_sides_to_zero(self, tmp_path: Path) -> None:
        out = _lua_to_hyprlang(
            tmp_path,
            "hl.workspace_rule({workspace = 1, gaps_in = {top = 5, bottom = 10}})",
        )
        # Right and left missing → 0.
        assert "gapsin:5 0 10 0" in out


# ---------------------------------------------------------------------------
# Round-trip stability — Hyprlang → Lua → Hyprlang and back
# ---------------------------------------------------------------------------


@requires_lua
class TestWorkspaceRoundTrip:
    """A rule's logical content is preserved through Hyprlang → Lua → Hyprlang."""

    def test_full_field_round_trip(self, tmp_path: Path) -> None:
        source = (
            "workspace = 1, monitor:DP-2, default:true, persistent:true, "
            "gapsin:5 10 5 10, gapsout:0, bordersize:2, border:false, "
            "rounding:false, shadow:true, decorate:false, defaultName:work, "
            "on-created-empty:kitty, layout:scrolling, layoutopt:direction:right\n"
        )
        # Hyprlang → Lua
        lua_path = tmp_path / "out.lua"
        lua_path.write_text(serialize_any(parse_string(source, lenient=True), lua_path))
        # Lua → Hyprlang
        back = serialize_hyprlang(load_lua(lua_path))
        # Every field survives — order-independent comparison since the
        # emitter sorts keys alphabetically.
        for token in [
            "monitor:DP-2",
            "default:true",
            "persistent:true",
            "gapsin:5 10 5 10",
            "gapsout:0",
            "bordersize:2",
            "border:false",
            "rounding:false",
            "shadow:true",
            "decorate:false",
            "defaultName:work",
            "on-created-empty:kitty",
            "layout:scrolling",
            "layoutopt:direction:right",
        ]:
            assert token in back, f"{token!r} missing from round-trip output:\n{back}"

    def test_selector_shapes_round_trip(self, tmp_path: Path) -> None:
        # Numeric / named / range / per-monitor / special selectors all
        # survive a full Hyprlang ↔ Lua round-trip.
        source = (
            "workspace = 1, monitor:DP-1\n"
            "workspace = name:work, monitor:DP-2\n"
            "workspace = r[1-10], gapsin:3\n"
            "workspace = m[1], persistent:true\n"
            "workspace = special:scratchpad, on-created-empty:kitty\n"
        )
        lua_path = tmp_path / "out.lua"
        lua_path.write_text(serialize_any(parse_string(source, lenient=True), lua_path))
        back = serialize_hyprlang(load_lua(lua_path))
        for selector in ("workspace = 1,", "name:work", "r[1-10]", "m[1]", "special:scratchpad"):
            assert selector in back, f"selector {selector!r} lost in round-trip:\n{back}"


# ---------------------------------------------------------------------------
# Direct unit tests on the translation helpers
# ---------------------------------------------------------------------------


class TestTranslationHelpers:
    """Spot-check the per-field translators in isolation."""

    def test_lua_to_hyprlang_inverted_bool(self) -> None:
        assert lua_field_to_hyprlang("no_border", True) == ("border", "false")
        assert lua_field_to_hyprlang("no_border", False) == ("border", "true")

    def test_lua_to_hyprlang_scalar_gap(self) -> None:
        assert lua_field_to_hyprlang("gaps_in", 5) == ("gapsin", "5")

    def test_lua_to_hyprlang_table_gap(self) -> None:
        result = lua_field_to_hyprlang("gaps_out", {"top": 1, "right": 2, "bottom": 3, "left": 4})
        assert result == ("gapsout", "1 2 3 4")

    def test_lua_to_hyprlang_unknown_field_passthrough(self) -> None:
        assert lua_field_to_hyprlang("plugin_x", "hello") == ("plugin_x", "hello")

    def test_hyprlang_to_lua_inverted_bool(self) -> None:
        assert hyprlang_field_to_lua("border", "false") == ("no_border", True)
        assert hyprlang_field_to_lua("border", "true") == ("no_border", False)

    def test_hyprlang_to_lua_scalar_gap(self) -> None:
        assert hyprlang_field_to_lua("gapsin", "5") == ("gaps_in", 5)

    def test_hyprlang_to_lua_four_value_gap(self) -> None:
        name, value = hyprlang_field_to_lua("gapsout", "1 2 3 4")
        assert name == "gaps_out"
        assert value == {"top": 1, "right": 2, "bottom": 3, "left": 4}

    def test_hyprlang_to_lua_two_value_gap_css_shorthand(self) -> None:
        # CSS shorthand: 2 values = vertical horizontal.
        _, value = hyprlang_field_to_lua("gapsin", "5 10")
        assert value == {"top": 5, "right": 10, "bottom": 5, "left": 10}

    def test_hyprlang_to_lua_int_coercion(self) -> None:
        assert hyprlang_field_to_lua("bordersize", "3") == ("border_size", 3)

    def test_hyprlang_to_lua_unknown_field_passthrough(self) -> None:
        # Pass through with best-effort scalar coercion.
        assert hyprlang_field_to_lua("plugin_x", "42") == ("plugin_x", 42)
        assert hyprlang_field_to_lua("plugin_x", "true") == ("plugin_x", True)
        assert hyprlang_field_to_lua("plugin_x", "free text") == ("plugin_x", "free text")

    def test_parse_layoutopt_splits_key_and_value(self) -> None:
        assert parse_layoutopt("direction:right") == ("direction", "right")

    def test_parse_layoutopt_coerces_numeric_value(self) -> None:
        assert parse_layoutopt("foo:5") == ("foo", 5)

    def test_parse_layoutopt_rejects_missing_inner_colon(self) -> None:
        # No ``key:value`` colon — Hyprland treats this as a malformed rule.
        assert parse_layoutopt("direction") is None

    def test_format_layout_opts_sorts_and_renders_tokens(self) -> None:
        assert format_layout_opts({"foo": 5, "direction": "right"}) == [
            "layoutopt:direction:right",
            "layoutopt:foo:5",
        ]
