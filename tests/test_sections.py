"""Tests for section iteration API: Document.sections() and Document.section()."""

from hyprland_config import (
    Assignment,
    BlankLine,
    Comment,
    SectionClose,
    SectionOpen,
    parse_string,
)

SAMPLE_CONFIG = """\
$mainMod = SUPER

general {
    gaps_in = 5
    gaps_out = 10
    border_size = 2
}

decoration {
    rounding = 10
    blur {
        enabled = true
        size = 3
    }
}

input {
    kb_layout = us
    touchpad {
        natural_scroll = true
    }
}

bind = $mainMod, Q, killactive
"""


class TestSections:
    def test_list_sections(self):
        doc = parse_string(SAMPLE_CONFIG)
        assert doc.sections() == ["general", "decoration", "blur", "input", "touchpad"]

    def test_list_sections_empty_document(self):
        doc = parse_string("key = value\n")
        assert doc.sections() == []

    def test_list_sections_no_duplicates(self):
        text = "general {\n    a = 1\n}\ngeneral {\n    b = 2\n}\n"
        doc = parse_string(text)
        assert doc.sections() == ["general"]

    def test_list_sections_includes_nested(self):
        """Nested sections like blur inside decoration are also listed."""
        doc = parse_string(SAMPLE_CONFIG)
        secs = doc.sections()
        assert "blur" in secs
        assert "touchpad" in secs


class TestSection:
    def test_get_section_contents(self):
        doc = parse_string(SAMPLE_CONFIG)
        lines = doc.section("general")
        keys = [ln.key for ln in lines if isinstance(ln, Assignment)]
        assert keys == ["gaps_in", "gaps_out", "border_size"]

    def test_section_excludes_braces(self):
        doc = parse_string(SAMPLE_CONFIG)
        lines = doc.section("general")
        assert not any(isinstance(ln, (SectionOpen, SectionClose)) for ln in lines)

    def test_section_with_nested_subsection(self):
        doc = parse_string(SAMPLE_CONFIG)
        lines = doc.section("decoration")
        # Should include the nested blur section and its contents
        types = [type(ln).__name__ for ln in lines if not isinstance(ln, BlankLine)]
        assert "SectionOpen" in types  # blur {
        assert "SectionClose" in types  # }

    def test_section_not_found(self):
        doc = parse_string(SAMPLE_CONFIG)
        assert doc.section("nonexistent") == []

    def test_hyphenated_section_name(self):
        """Plugin sections like 'split-monitor-workspaces' use hyphens."""
        text = "split-monitor-workspaces {\n    count = 2\n    keep_focused = 1\n}\n"
        doc = parse_string(text)
        lines = doc.section("split-monitor-workspaces")
        assert len(lines) == 2
        assert isinstance(lines[0], Assignment)
        assert lines[0].key == "count"

    def test_keyed_section(self):
        text = (
            "device[epic-mouse-v1] {\n"
            "    sensitivity = -0.5\n"
            "}\n"
            "device[keyboard-k1] {\n"
            "    kb_layout = de\n"
            "}\n"
        )
        doc = parse_string(text)
        lines = doc.section("device", key="epic-mouse-v1")
        assert len(lines) == 1
        assert isinstance(lines[0], Assignment)
        assert lines[0].key == "sensitivity"

    def test_keyed_section_no_match(self):
        text = "device[mouse] {\n    sens = 1\n}\n"
        doc = parse_string(text)
        assert doc.section("device", key="keyboard") == []

    def test_section_without_key_gets_all(self):
        """When key is None, all sections with that name are merged."""
        text = "device[mouse] {\n    sens = 1\n}\ndevice[keyboard] {\n    layout = us\n}\n"
        doc = parse_string(text)
        lines = doc.section("device")
        keys = [ln.key for ln in lines if isinstance(ln, Assignment)]
        assert keys == ["sens", "layout"]

    def test_multiple_same_sections_merged(self):
        text = "general {\n    a = 1\n}\ngeneral {\n    b = 2\n}\n"
        doc = parse_string(text)
        lines = doc.section("general")
        keys = [ln.key for ln in lines if isinstance(ln, Assignment)]
        assert keys == ["a", "b"]

    def test_section_preserves_comments(self):
        text = "general {\n    # a comment\n    gaps_in = 5\n}\n"
        doc = parse_string(text)
        lines = doc.section("general")
        assert any(isinstance(ln, Comment) for ln in lines)
