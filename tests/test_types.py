"""Tests for typed value parsing — Color, Gradient, Vec2."""

import pytest

from hyprland_config import Color, Gradient, Vec2


class TestColor:
    def test_parse_rgba(self):
        c = Color.parse("rgba(33ccffee)")
        assert c == Color(r=0x33, g=0xCC, b=0xFF, a=0xEE)

    def test_parse_rgb(self):
        c = Color.parse("rgb(33ccff)")
        assert c == Color(r=0x33, g=0xCC, b=0xFF, a=255)

    def test_parse_hex(self):
        c = Color.parse("0xee33ccff")
        assert c == Color(r=0x33, g=0xCC, b=0xFF, a=0xEE)

    def test_parse_strips_whitespace(self):
        c = Color.parse("  rgba(33ccffee)  ")
        assert c == Color(r=0x33, g=0xCC, b=0xFF, a=0xEE)

    def test_parse_uppercase(self):
        c = Color.parse("rgba(33CCFFEE)")
        assert c == Color(r=0x33, g=0xCC, b=0xFF, a=0xEE)

    def test_parse_invalid_raises(self):
        with pytest.raises(ValueError, match="Cannot parse color"):
            Color.parse("not_a_color")

    def test_parse_empty_raises(self):
        with pytest.raises(ValueError):
            Color.parse("")

    def test_to_rgba(self):
        c = Color(r=0x33, g=0xCC, b=0xFF, a=0xEE)
        assert c.to_rgba() == "rgba(33ccffee)"

    def test_to_rgb(self):
        c = Color(r=0x33, g=0xCC, b=0xFF, a=0xEE)
        assert c.to_rgb() == "rgb(33ccff)"

    def test_to_hex(self):
        c = Color(r=0x33, g=0xCC, b=0xFF, a=0xEE)
        assert c.to_hex() == "0xee33ccff"

    def test_roundtrip_rgba(self):
        original = "rgba(33ccffee)"
        assert Color.parse(original).to_rgba() == original

    def test_roundtrip_hex(self):
        original = "0xee33ccff"
        assert Color.parse(original).to_hex() == original

    def test_black_transparent(self):
        c = Color.parse("rgba(00000000)")
        assert c == Color(r=0, g=0, b=0, a=0)

    def test_white_opaque(self):
        c = Color.parse("rgb(ffffff)")
        assert c == Color(r=255, g=255, b=255, a=255)


class TestGradient:
    def test_parse_two_colors_with_angle(self):
        g = Gradient.parse("rgba(33ccffee) rgba(00ff99ee) 45deg")
        assert len(g.colors) == 2
        assert g.colors[0] == Color.parse("rgba(33ccffee)")
        assert g.colors[1] == Color.parse("rgba(00ff99ee)")
        assert g.angle == 45

    def test_parse_single_color(self):
        g = Gradient.parse("rgb(ff0000)")
        assert len(g.colors) == 1
        assert g.angle == 0

    def test_parse_no_angle(self):
        g = Gradient.parse("rgba(33ccffee) rgba(00ff99ee)")
        assert g.angle == 0

    def test_parse_three_colors(self):
        g = Gradient.parse("rgb(ff0000) rgb(00ff00) rgb(0000ff) 90deg")
        assert len(g.colors) == 3
        assert g.angle == 90

    def test_parse_empty_raises(self):
        with pytest.raises(ValueError):
            Gradient.parse("")

    def test_str_with_angle(self):
        g = Gradient(colors=(Color(255, 0, 0), Color(0, 255, 0)), angle=45)
        assert str(g) == "rgba(ff0000ff) rgba(00ff00ff) 45deg"

    def test_str_no_angle(self):
        g = Gradient(colors=(Color(255, 0, 0),), angle=0)
        assert str(g) == "rgba(ff0000ff)"

    def test_roundtrip(self):
        original = "rgba(33ccffee) rgba(00ff99ee) 45deg"
        assert str(Gradient.parse(original)) == original


class TestVec2:
    def test_parse_integers(self):
        v = Vec2.parse("1920 1080")
        assert v == Vec2(x=1920, y=1080)

    def test_parse_floats(self):
        v = Vec2.parse("2.5 3.7")
        assert v == Vec2(x=2.5, y=3.7)

    def test_parse_mixed(self):
        v = Vec2.parse("0 1080")
        assert v == Vec2(x=0, y=1080)

    def test_parse_negative(self):
        v = Vec2.parse("-100 200")
        assert v == Vec2(x=-100, y=200)

    def test_parse_strips_whitespace(self):
        v = Vec2.parse("  1920  1080  ")
        assert v == Vec2(x=1920, y=1080)

    def test_parse_too_few_raises(self):
        with pytest.raises(ValueError, match="expected 2 values"):
            Vec2.parse("1920")

    def test_parse_too_many_raises(self):
        with pytest.raises(ValueError, match="expected 2 values"):
            Vec2.parse("1 2 3")

    def test_parse_non_numeric_raises(self):
        with pytest.raises(ValueError, match="non-numeric"):
            Vec2.parse("abc def")

    def test_str(self):
        v = Vec2(x=1920, y=1080)
        assert str(v) == "1920 1080"

    def test_str_float(self):
        v = Vec2(x=2.5, y=3.7)
        assert str(v) == "2.5 3.7"

    def test_int_conversion(self):
        """Whole-number floats are stored as int."""
        v = Vec2.parse("1920.0 1080.0")
        assert v.x == 1920
        assert v.y == 1080
        assert isinstance(v.x, int)
        assert isinstance(v.y, int)
