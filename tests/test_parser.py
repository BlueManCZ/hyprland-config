"""Tests for line classification, round-trip serialization, and parse errors."""

from pathlib import Path

import pytest

from hyprland_config import (
    Assignment,
    BlankLine,
    Comment,
    Keyword,
    ParseError,
    SectionClose,
    SectionOpen,
    Source,
    Variable,
    parse_string,
)

# ---------------------------------------------------------------------------
# Round-trip: serialize(parse(text)) == text
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_empty(self):
        doc = parse_string("")
        assert doc.serialize() == ""

    def test_blank_lines(self):
        text = "\n\n\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_comments(self):
        text = "# This is a comment\n# Another comment\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_simple_assignment(self):
        text = "gaps_in = 5\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_section_block(self):
        text = "general {\n    gaps_in = 5\n    gaps_out = 10\n}\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_nested_sections(self):
        text = "decoration {\n    shadow {\n        range = 10\n    }\n}\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_variable_definition(self):
        text = "$mainMod = SUPER\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_variable_with_hyphen(self):
        text = "$terminal-float = kitty --class kitty-floating\n"
        doc = parse_string(text)
        assert doc.serialize() == text
        assert doc.variables["terminal-float"] == "kitty --class kitty-floating"

    def test_bind_keyword(self):
        text = "bind = SUPER, Q, killactive,\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_source_directive(self):
        text = "source = ~/.config/hypr/hyprland.conf.d/*\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_inline_comment(self):
        text = "bind = $mainMod, P, pseudo # dwindle\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_env_keyword(self):
        text = "env = LIBVA_DRIVER_NAME,nvidia\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_monitor_keyword(self):
        text = "monitor = DP-2, 3440x1440@165, 0x0, 1, bitdepth, 10, cm, srgb\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_exec_once(self):
        text = "exec-once = ~/.config/hypr/autostart.sh\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_workspace_keyword(self):
        text = "workspace = 1, monitor:DP-2, default:true\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_windowrule(self):
        text = "windowrule = float on, match:class Electron\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_no_trailing_newline(self):
        text = "key = value"
        doc = parse_string(text)
        assert doc.serialize() == text


# ---------------------------------------------------------------------------
# Round-trip against real config files
# ---------------------------------------------------------------------------


class TestRealConfigs:
    """Round-trip test against actual Hyprland config files."""

    @pytest.fixture
    def conf_dir(self):
        d = Path.home() / ".config" / "hypr"
        if not d.exists():
            pytest.skip("No Hyprland config directory found")
        return d

    def _all_conf_files(self, conf_dir: Path):
        files = list(conf_dir.rglob("*.conf"))
        if not files:
            pytest.skip("No .conf files found")
        return files

    def test_round_trip_all(self, conf_dir):
        files = self._all_conf_files(conf_dir)
        for path in files:
            text = path.read_text()
            doc = parse_string(text, name=str(path))
            result = doc.serialize()
            assert result == text, f"Round-trip failed for {path}"


# ---------------------------------------------------------------------------
# Node classification
# ---------------------------------------------------------------------------


class TestClassification:
    def test_blank_line(self):
        doc = parse_string("\n")
        assert isinstance(doc.lines[0], BlankLine)

    def test_comment(self):
        doc = parse_string("# hello\n")
        assert isinstance(doc.lines[0], Comment)
        assert doc.lines[0].text == "hello"

    def test_variable(self):
        doc = parse_string("$mainMod = SUPER\n")
        node = doc.lines[0]
        assert isinstance(node, Variable)
        assert node.name == "mainMod"
        assert node.value == "SUPER"

    def test_source(self):
        doc = parse_string("source = ~/path/to/file.conf\n")
        node = doc.lines[0]
        assert isinstance(node, Source)
        assert node.path_str == "~/path/to/file.conf"

    def test_section_open(self):
        doc = parse_string("general {\n")
        node = doc.lines[0]
        assert isinstance(node, SectionOpen)
        assert node.name == "general"

    def test_section_open_with_colon(self):
        doc = parse_string("plugin:dynamic-cursors {\n    shake_threshold = 3\n}\n")
        node = doc.lines[0]
        assert isinstance(node, SectionOpen)
        assert node.name == "plugin:dynamic-cursors"
        assignment = doc.lines[1]
        assert isinstance(assignment, Assignment)
        assert assignment.full_key == "plugin:dynamic-cursors:shake_threshold"

    def test_section_open_with_key(self):
        doc = parse_string("device[my-mouse] {\n")
        node = doc.lines[0]
        assert isinstance(node, SectionOpen)
        assert node.name == "device"
        assert node.section_key == "my-mouse"

    def test_section_close(self):
        doc = parse_string("}\n")
        assert isinstance(doc.lines[0], SectionClose)

    def test_assignment_in_section(self):
        doc = parse_string("general {\n    gaps_in = 5\n}\n")
        assert isinstance(doc.lines[1], Assignment)
        assert doc.lines[1].key == "gaps_in"
        assert doc.lines[1].value == "5"
        assert doc.lines[1].full_key == "general:gaps_in"

    def test_nested_section_full_key(self):
        doc = parse_string("decoration {\n    shadow {\n        range = 10\n    }\n}\n")
        assignment = doc.lines[2]
        assert isinstance(assignment, Assignment)
        assert assignment.full_key == "decoration:shadow:range"

    def test_bind_keyword(self):
        doc = parse_string("bind = SUPER, Q, killactive,\n")
        node = doc.lines[0]
        assert isinstance(node, Keyword)
        assert node.key == "bind"

    def test_inline_category_syntax(self):
        doc = parse_string("general:gaps_in = 5\n")
        node = doc.lines[0]
        assert isinstance(node, Assignment)
        assert node.full_key == "general:gaps_in"

    def test_animation_in_section(self):
        text = "animations {\n    animation = windows, 1, 3, myBezier\n}\n"
        doc = parse_string(text)
        node = doc.lines[1]
        assert isinstance(node, Keyword)
        assert node.key == "animation"
        assert node.full_key == "animations:animation"

    def test_bezier_in_section(self):
        text = "animations {\n    bezier = myBezier, 0.05, 0.9, 0.1, 1.05\n}\n"
        doc = parse_string(text)
        node = doc.lines[1]
        assert isinstance(node, Keyword)
        assert node.key == "bezier"


# ---------------------------------------------------------------------------
# Inline comments
# ---------------------------------------------------------------------------


class TestInlineComments:
    def test_assignment_inline_comment(self):
        doc = parse_string("key = value # comment\n")
        node = doc.lines[0]
        assert isinstance(node, Assignment)
        assert node.value == "value"
        assert node.inline_comment == "# comment"

    def test_keyword_inline_comment(self):
        doc = parse_string("bind = $mainMod, P, pseudo # dwindle\n")
        node = doc.lines[0]
        assert isinstance(node, Keyword)
        assert node.inline_comment == "# dwindle"


class TestEscapedHash:
    """Tests for ## escape producing literal # in values."""

    def test_escaped_hash_in_value(self):
        doc = parse_string("key = value with ## embedded hash\n")
        node = doc.lines[0]
        assert isinstance(node, Assignment)
        assert node.value == "value with ## embedded hash"
        assert node.inline_comment == ""

    def test_url_with_escaped_hash_and_trailing_comment(self):
        doc = parse_string("key = https://example.com ## trailing\n")
        node = doc.lines[0]
        assert isinstance(node, Assignment)
        assert node.value == "https://example.com ## trailing"
        assert node.inline_comment == ""

    def test_escaped_hash_before_real_comment(self):
        doc = parse_string("key = color ## hex # this is comment\n")
        node = doc.lines[0]
        assert isinstance(node, Assignment)
        assert node.value == "color ## hex"
        assert node.inline_comment == "# this is comment"

    def test_multiple_escaped_hashes(self):
        doc = parse_string("key = a ## b ## c\n")
        node = doc.lines[0]
        assert isinstance(node, Assignment)
        assert node.value == "a ## b ## c"
        assert node.inline_comment == ""

    def test_escaped_hash_round_trip(self):
        text = "key = value with ## hash\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_escaped_hash_round_trip_with_comment(self):
        text = "key = val ## lit # comment\n"
        doc = parse_string(text)
        assert doc.serialize() == text


# ---------------------------------------------------------------------------
# One-line blocks
# ---------------------------------------------------------------------------


class TestOneLineBlocks:
    def test_one_line_block(self):
        doc = parse_string("general { gaps_in = 5 }\n")
        assert doc.serialize() == "general { gaps_in = 5 }\n"
        node = doc.lines[0]
        assert isinstance(node, Assignment)
        assert node.full_key == "general:gaps_in"
        assert node.value == "5"


# ---------------------------------------------------------------------------
# Error reporting
# ---------------------------------------------------------------------------


class TestParseError:
    def test_unparseable_line_raises(self):
        with pytest.raises(ParseError, match="could not parse"):
            parse_string("@@@ not valid hyprlang\n")

    def test_error_includes_line_number(self):
        with pytest.raises(ParseError) as exc_info:
            parse_string("key = value\n@@@ bad\n")
        assert exc_info.value.lineno == 2

    def test_error_includes_source_name(self):
        with pytest.raises(ParseError) as exc_info:
            parse_string("@@@ bad\n", name="test.conf")
        assert "test.conf" in str(exc_info.value)
        assert exc_info.value.source_name == "test.conf"
