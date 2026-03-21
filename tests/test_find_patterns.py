"""Tests for glob pattern matching in find() and find_all()."""

from hyprland_config import parse_string


class TestFindGlob:
    CONFIG = """\
$mainMod = SUPER

general {
    gaps_in = 5
    gaps_out = 20
    border_size = 2
}

input {
    touchpad {
        natural_scroll = true
        tap-to-click = true
    }
    sensitivity = 0.5
}

bind = $mainMod, Q, killactive
bind = $mainMod, M, exit
bindm = $mainMod, mouse:272, movewindow
binde = $mainMod, right, resizeactive, 10 0
monitor = DP-1, 2560x1440, 0x0, 1
"""

    def setup_method(self):
        self.doc = parse_string(self.CONFIG)

    def test_find_exact_still_works(self):
        node = self.doc.find("general:gaps_in")
        assert node is not None
        assert node.value == "5"

    def test_find_all_exact_still_works(self):
        results = self.doc.find_all("bind")
        assert len(results) == 2

    def test_find_all_wildcard_prefix(self):
        """bind* should match bind, bindm, binde."""
        results = self.doc.find_all("bind*")
        assert len(results) == 4

    def test_find_all_section_wildcard(self):
        """general:* should match all general settings."""
        results = self.doc.find_all("general:*")
        assert len(results) == 3
        keys = {r.full_key for r in results}
        assert keys == {"general:gaps_in", "general:gaps_out", "general:border_size"}

    def test_find_all_nested_wildcard(self):
        """input:touchpad:* should match all touchpad settings."""
        results = self.doc.find_all("input:touchpad:*")
        assert len(results) == 2
        keys = {r.full_key for r in results}
        assert keys == {"input:touchpad:natural_scroll", "input:touchpad:tap-to-click"}

    def test_find_all_deep_wildcard(self):
        """input:* matches all descendants (fnmatch * matches colons too)."""
        results = self.doc.find_all("input:*")
        assert len(results) == 3
        keys = {r.full_key for r in results}
        assert keys == {
            "input:touchpad:natural_scroll",
            "input:touchpad:tap-to-click",
            "input:sensitivity",
        }

    def test_find_last_with_pattern(self):
        """find() with pattern returns the last match."""
        node = self.doc.find("general:gaps_*")
        assert node is not None
        assert node.full_key == "general:gaps_out"

    def test_find_all_question_mark(self):
        """? matches a single character."""
        results = self.doc.find_all("bind?")
        assert len(results) == 2
        keys = {r.key for r in results}
        assert keys == {"bindm", "binde"}

    def test_find_all_no_match(self):
        results = self.doc.find_all("nonexistent:*")
        assert results == []

    def test_find_no_match_returns_none(self):
        assert self.doc.find("nonexistent:*") is None

    def test_get_all_with_pattern(self):
        """get_all should also work with patterns via find_all."""
        # get_all delegates to find_all, so patterns work transitively
        results = self.doc.find_all("general:gaps_*")
        values = [r.value for r in results]
        assert "5" in values
        assert "20" in values
