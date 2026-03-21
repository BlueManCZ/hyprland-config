"""Tests for conditional directive parsing (# hyprlang if/elif/else/endif)."""

from hyprland_config import (
    Comment,
    Conditional,
    parse_string,
)


class TestConditionalParsing:
    """Conditional directives are recognised as Conditional nodes, not Comment."""

    def test_if_directive(self):
        doc = parse_string("# hyprlang if $MONITOR_COUNT > 1\n")
        node = doc.lines[0]
        assert isinstance(node, Conditional)
        assert node.kind == "if"
        assert node.expression == "$MONITOR_COUNT > 1"

    def test_elif_directive(self):
        doc = parse_string("# hyprlang elif $GPU == nvidia\n")
        node = doc.lines[0]
        assert isinstance(node, Conditional)
        assert node.kind == "elif"
        assert node.expression == "$GPU == nvidia"

    def test_else_directive(self):
        doc = parse_string("# hyprlang else\n")
        node = doc.lines[0]
        assert isinstance(node, Conditional)
        assert node.kind == "else"
        assert node.expression == ""

    def test_endif_directive(self):
        doc = parse_string("# hyprlang endif\n")
        node = doc.lines[0]
        assert isinstance(node, Conditional)
        assert node.kind == "endif"
        assert node.expression == ""

    def test_extra_whitespace(self):
        doc = parse_string("#  hyprlang   if   $x > 0\n")
        node = doc.lines[0]
        assert isinstance(node, Conditional)
        assert node.kind == "if"
        assert node.expression == "$x > 0"

    def test_regular_comment_not_conditional(self):
        doc = parse_string("# this is a regular comment\n")
        assert isinstance(doc.lines[0], Comment)

    def test_hyprlang_without_keyword_is_comment(self):
        doc = parse_string("# hyprlang something_else foo\n")
        assert isinstance(doc.lines[0], Comment)


class TestNoerrorDirective:
    """Tests for # hyprlang noerror true/false directive."""

    def test_noerror_true(self):
        doc = parse_string("# hyprlang noerror true\n")
        node = doc.lines[0]
        assert isinstance(node, Conditional)
        assert node.kind == "noerror"
        assert node.expression == "true"

    def test_noerror_false(self):
        doc = parse_string("# hyprlang noerror false\n")
        node = doc.lines[0]
        assert isinstance(node, Conditional)
        assert node.kind == "noerror"
        assert node.expression == "false"

    def test_noerror_round_trip(self):
        text = "# hyprlang noerror true\nbind = MOD, KEY, exec, cmd\n# hyprlang noerror false\n"
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_noerror_not_a_comment(self):
        doc = parse_string("# hyprlang noerror true\n")
        assert not isinstance(doc.lines[0], Comment)


class TestConditionalRoundTrip:
    """Conditional directives survive serialization unchanged."""

    def test_full_block_round_trip(self):
        text = (
            "# hyprlang if $MONITOR_COUNT > 1\n"
            "monitor = DP-1, 2560x1440, 0x0, 1\n"
            "# hyprlang else\n"
            "monitor = eDP-1, preferred, auto, 1\n"
            "# hyprlang endif\n"
        )
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_nested_conditionals_round_trip(self):
        text = (
            "# hyprlang if $X > 0\n"
            "# hyprlang if $Y > 0\n"
            "key = both_positive\n"
            "# hyprlang endif\n"
            "# hyprlang endif\n"
        )
        doc = parse_string(text)
        assert doc.serialize() == text

    def test_elif_chain_round_trip(self):
        text = (
            "# hyprlang if $GPU == nvidia\n"
            "env = __GLX_VENDOR_LIBRARY_NAME, nvidia\n"
            "# hyprlang elif $GPU == amd\n"
            "env = AMD_VULKAN_ICD, RADV\n"
            "# hyprlang else\n"
            "# no GPU-specific config\n"
            "# hyprlang endif\n"
        )
        doc = parse_string(text)
        assert doc.serialize() == text


class TestConditionalNodeTypes:
    """Verify node types in a full conditional block."""

    def test_block_node_sequence(self):
        text = "# hyprlang if $X > 0\nkey = value\n# hyprlang else\nkey = other\n# hyprlang endif\n"
        doc = parse_string(text)
        types = [type(ln).__name__ for ln in doc.lines]
        assert types == ["Conditional", "Assignment", "Conditional", "Assignment", "Conditional"]

        # Verify specific conditional properties
        assert isinstance(doc.lines[0], Conditional) and doc.lines[0].kind == "if"
        assert isinstance(doc.lines[2], Conditional) and doc.lines[2].kind == "else"
        assert isinstance(doc.lines[4], Conditional) and doc.lines[4].kind == "endif"

    def test_conditional_preserves_lineno(self):
        text = "key = val\n# hyprlang if $x > 0\nother = 1\n# hyprlang endif\n"
        doc = parse_string(text)
        cond = doc.lines[1]
        assert isinstance(cond, Conditional)
        assert cond.lineno == 2

    def test_conditional_mixed_with_sections(self):
        text = "general {\n    # hyprlang if $GAPS\n    gaps_in = 5\n    # hyprlang endif\n}\n"
        doc = parse_string(text)
        assert isinstance(doc.lines[1], Conditional)
        assert doc.lines[1].kind == "if"
        assert isinstance(doc.lines[3], Conditional)
        assert doc.lines[3].kind == "endif"
        assert doc.serialize() == text
