"""Tests for lenient parsing mode (malformed input tolerance)."""

from pathlib import Path

import pytest

from hyprland_config import ErrorLine, load, parse_string
from hyprland_config._parser import ParseError, parse_file


class TestLenientParsing:
    """Lenient mode collects errors instead of raising."""

    def test_strict_mode_raises_on_bad_line(self):
        with pytest.raises(ParseError, match="could not parse"):
            parse_string("@@@ garbage\n")

    def test_lenient_mode_does_not_raise(self):
        doc = parse_string("@@@ garbage\n", lenient=True)
        assert len(doc.lines) == 1

    def test_error_line_preserves_raw_text(self):
        doc = parse_string("@@@ garbage\n", lenient=True)
        assert doc.lines[0].raw == "@@@ garbage\n"

    def test_error_line_has_message(self):
        doc = parse_string("@@@ garbage\n", lenient=True)
        error = doc.lines[0]
        assert isinstance(error, ErrorLine)
        assert "could not parse" in error.message

    def test_error_line_has_lineno(self):
        doc = parse_string("key = ok\n@@@ bad\n", lenient=True)
        error = doc.errors[0]
        assert error.lineno == 2

    def test_error_line_has_source_name(self):
        doc = parse_string("@@@ bad\n", name="test.conf", lenient=True)
        error = doc.errors[0]
        assert error.source_name == "test.conf"

    def test_errors_property_lists_all_errors(self):
        text = "key = ok\n@@@ bad1\nother = fine\n@@@ bad2\n"
        doc = parse_string(text, lenient=True)
        assert len(doc.errors) == 2
        assert "bad1" in doc.errors[0].message
        assert "bad2" in doc.errors[1].message

    def test_valid_lines_still_parsed(self):
        text = "key = value\n@@@ bad\nother = ok\n"
        doc = parse_string(text, lenient=True)
        assert doc.get("key") == "value"
        assert doc.get("other") == "ok"

    def test_no_errors_on_valid_config(self):
        text = "general {\n    gaps_in = 5\n}\n"
        doc = parse_string(text, lenient=True)
        assert doc.errors == []

    def test_variables_still_collected(self):
        text = "$mainMod = SUPER\n@@@ bad\nbind = $mainMod, Q, killactive\n"
        doc = parse_string(text, lenient=True)
        assert doc.variables["mainMod"] == "SUPER"


class TestLenientRoundTrip:
    """Error lines are preserved in round-trip serialization."""

    def test_serialize_preserves_error_lines(self):
        text = "key = value\n@@@ bad\nother = ok\n"
        doc = parse_string(text, lenient=True)
        assert doc.serialize() == text

    def test_serialize_mixed_errors_and_sections(self):
        text = "general {\n    gaps_in = 5\n    @@@ bad\n}\n"
        doc = parse_string(text, lenient=True)
        assert doc.serialize() == text


class TestLenientMultipleIssues:
    """Lenient mode reports multiple issues at once."""

    def test_missing_close_brace_and_bad_lines(self):
        text = "key = ok\n@@@ err1\n@@@ err2\n@@@ err3\n"
        doc = parse_string(text, lenient=True)
        assert len(doc.errors) == 3

    def test_trailing_garbage(self):
        text = "key = value\nrandom text without equals\n"
        doc = parse_string(text, lenient=True)
        assert len(doc.errors) == 1
        assert doc.get("key") == "value"


class TestLenientParseFile:
    """Lenient mode works with parse_file."""

    def test_lenient_parse_file(self, tmp_path: Path):
        conf = tmp_path / "test.conf"
        conf.write_text("key = ok\n@@@ bad\nother = fine\n")
        doc = parse_file(conf, lenient=True)
        assert len(doc.errors) == 1
        assert doc.get("key") == "ok"
        assert doc.get("other") == "fine"

    def test_lenient_with_follow_sources(self, tmp_path: Path):
        sub = tmp_path / "sub.conf"
        sub.write_text("@@@ sub_error\nsubkey = val\n")
        main = tmp_path / "main.conf"
        main.write_text(f"key = ok\nsource = {sub}\n")
        doc = parse_file(main, follow_sources=True, lenient=True)
        assert len(doc.errors) == 1
        assert "sub_error" in doc.errors[0].message

    def test_lenient_load(self, tmp_path: Path):
        conf = tmp_path / "hyprland.conf"
        conf.write_text("key = ok\n@@@ bad\n")
        doc = load(conf, lenient=True)
        assert len(doc.errors) == 1
        assert doc.get("key") == "ok"
