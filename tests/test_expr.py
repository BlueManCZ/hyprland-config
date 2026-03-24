"""Tests for expression evaluation ({{expr}} syntax)."""

import pytest

from hyprland_config import parse_string
from hyprland_config._expr import ExprError, evaluate, expand_expressions


class TestEvaluate:
    def test_simple_int(self):
        assert evaluate("5") == 5

    def test_simple_float(self):
        assert evaluate("3.14") == 3.14

    def test_addition(self):
        assert evaluate("5 + 2") == 7

    def test_subtraction(self):
        assert evaluate("10 - 3") == 7

    def test_multiplication(self):
        assert evaluate("4 * 3") == 12

    def test_division(self):
        assert evaluate("10 / 4") == 2.5

    def test_integer_division_result(self):
        assert evaluate("10 / 2") == 5
        assert isinstance(evaluate("10 / 2"), int)

    def test_modulo(self):
        assert evaluate("10 % 3") == 1

    def test_parentheses(self):
        assert evaluate("(2 + 3) * 4") == 20

    def test_nested_parentheses(self):
        assert evaluate("((2 + 3) * (4 - 1))") == 15

    def test_operator_precedence(self):
        assert evaluate("2 + 3 * 4") == 14

    def test_unary_minus(self):
        assert evaluate("-5") == -5

    def test_unary_minus_in_expr(self):
        assert evaluate("10 + -3") == 7

    def test_unary_plus(self):
        assert evaluate("+5") == 5

    def test_division_by_zero(self):
        with pytest.raises(ExprError, match="division by zero"):
            evaluate("1 / 0")

    def test_modulo_by_zero(self):
        with pytest.raises(ExprError, match="modulo by zero"):
            evaluate("1 % 0")

    def test_empty_expression(self):
        with pytest.raises(ExprError, match="empty expression"):
            evaluate("")

    def test_invalid_character(self):
        with pytest.raises(ExprError):
            evaluate("5 & 3")

    def test_missing_closing_paren(self):
        with pytest.raises(ExprError, match="missing closing parenthesis"):
            evaluate("(2 + 3")

    def test_whitespace_handling(self):
        assert evaluate("  5 + 2  ") == 7

    def test_no_spaces(self):
        assert evaluate("5+2") == 7


class TestExpandExpressions:
    def test_single_expression(self):
        assert expand_expressions("{{5 + 2}}") == "7"

    def test_expression_in_text(self):
        assert expand_expressions("gaps_in = {{5 + 2}}") == "gaps_in = 7"

    def test_multiple_expressions(self):
        assert expand_expressions("{{1 + 2}} and {{3 * 4}}") == "3 and 12"

    def test_no_expressions(self):
        assert expand_expressions("plain text") == "plain text"

    def test_invalid_expression_left_unchanged(self):
        assert expand_expressions("{{invalid}}") == "{{invalid}}"

    def test_float_result(self):
        assert expand_expressions("{{10 / 3}}") == str(10 / 3)


class TestExpressionEscaping:
    """Tests for backslash escaping of {{expr}} (hyprlang 0.6.4+)."""

    def test_backslash_before_opening_braces(self):
        assert expand_expressions("\\{{10 + 10}}") == "{{10 + 10}}"

    def test_backslash_between_opening_braces(self):
        assert expand_expressions("{\\{10 + 10}}") == "{{10 + 10}}"

    def test_backslash_before_both_opening_braces(self):
        assert expand_expressions("\\{\\{10 + 10}}") == "{{10 + 10}}"

    def test_double_backslash_before_expression(self):
        assert expand_expressions("\\\\{{10 + 10}}") == "\\20"

    def test_double_backslash_with_literal_braces(self):
        assert expand_expressions("\\\\{ hello \\\\}") == "\\{ hello \\}"

    def test_escaped_and_real_expression_mixed(self):
        assert expand_expressions("text \\{{a}} and {{1 + 2}}") == "text {{a}} and 3"

    def test_backslash_at_end_of_string(self):
        assert expand_expressions("trailing\\") == "trailing\\"

    def test_no_escapes_no_expressions(self):
        assert expand_expressions("plain text") == "plain text"

    def test_backslash_before_non_brace(self):
        assert expand_expressions("hello\\nworld") == "hello\\nworld"

    def test_lone_backslash_brace_no_expression(self):
        assert expand_expressions("\\{not an expr") == "{not an expr"

    def test_double_backslash_alone(self):
        assert expand_expressions("path\\\\end") == "path\\end"


class TestExpressionWithVariables:
    """Test that expressions work correctly after variable expansion."""

    def test_variable_in_expression(self):
        doc = parse_string("$gap = 5\n")
        result = doc.expand("{{$gap + 2}}")
        assert result == "7"

    def test_expression_in_config_value(self):
        doc = parse_string("$gap = 5\ngeneral {\n    gaps_in = {{$gap + 2}}\n}\n")
        flat = doc.to_dict()
        assert flat["general:gaps_in"] == "7"

    def test_multiple_variables_in_expression(self):
        doc = parse_string("$a = 10\n$b = 3\n")
        result = doc.expand("{{$a * $b}}")
        assert result == "30"

    def test_expression_with_parentheses_and_vars(self):
        doc = parse_string("$gap = 5\n$mult = 2\n")
        result = doc.expand("{{($gap + 3) * $mult}}")
        assert result == "16"

    def test_escaped_expression_with_variables(self):
        doc = parse_string("$gap = 5\n")
        result = doc.expand("\\{{$gap + 2}}")
        assert result == "{{5 + 2}}"

    def test_escaped_vs_real_in_to_dict(self):
        doc = parse_string(
            "$gap = 5\ngeneral {\n    gaps_in = {{$gap + 2}}\n    label = \\{{$gap + 2}}\n}\n"
        )
        flat = doc.to_dict()
        assert flat["general:gaps_in"] == "7"
        assert flat["general:label"] == "{{5 + 2}}"
