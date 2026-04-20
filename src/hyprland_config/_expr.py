"""Expression evaluator for Hyprland {{expr}} syntax.

Supports integer and float arithmetic: +, -, *, /, %, parentheses.
Variable references ($var) should be expanded before evaluation.
"""

import ast
import operator
from typing import Callable

_BIN_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}

_UNARY_OPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class ExprError(Exception):
    """Raised when an expression cannot be evaluated."""


def _eval_node(node: ast.AST) -> int | float:
    """Recursively evaluate an AST node, allowing only arithmetic on numeric constants."""
    if isinstance(node, ast.Constant):
        # bool is a subclass of int — reject so True/False aren't treated as numbers
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExprError(f"unsupported literal: {node.value!r}")
        return node.value
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ExprError(f"unsupported operator: {type(node.op).__name__}")
        try:
            return op(_eval_node(node.left), _eval_node(node.right))
        except ZeroDivisionError:
            name = "division" if isinstance(node.op, ast.Div) else "modulo"
            raise ExprError(f"{name} by zero") from None
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ExprError(f"unsupported unary operator: {type(node.op).__name__}")
        return op(_eval_node(node.operand))
    raise ExprError(f"unsupported expression node: {type(node).__name__}")


def evaluate(expr: str) -> int | float:
    """Evaluate a simple arithmetic expression.

    Returns int when the result is a whole number, float otherwise.
    """
    expr = expr.strip()
    if not expr:
        raise ExprError("empty expression")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        msg = e.msg or str(e)
        if "never closed" in msg:
            raise ExprError("missing closing parenthesis") from None
        raise ExprError(f"invalid expression: {msg}") from None
    result = _eval_node(tree.body)
    # Return int when possible for cleaner output
    if isinstance(result, float) and result.is_integer():
        return int(result)
    return result


def expand_value(text: str, variables: dict[str, str]) -> str:
    """Fully expand a Hyprland config value.

    Performs three transformations in order:
    1. Variable substitution — ``$var`` references are replaced
       longest-name-first to avoid prefix collisions.
    2. Expression evaluation — ``{{expr}}`` blocks are evaluated as
       arithmetic expressions.
    3. Escape processing — backslash escapes (``\\\\``, ``\\{``) are
       resolved per hyprlang 0.6.4+ rules.
    """
    result = text
    for name in sorted(variables, key=len, reverse=True):
        result = result.replace(f"${name}", variables[name])
    if "{{" in result or "\\" in result:
        result = expand_expressions(result)
    return result


def expand_expressions(text: str) -> str:
    """Replace all ``{{expr}}`` in text with their evaluated results.

    Handles escape sequences (hyprlang 0.6.4+):

    - ``\\{{expr}}`` or ``{\\{expr}}`` or ``\\{\\{expr}}`` prevents
      evaluation; the backslashes are stripped and ``{{expr}}`` is
      kept verbatim.
    - ``\\\\{{expr}}`` produces a literal backslash followed by the
      evaluated expression result.

    Expressions that fail to evaluate are left unchanged.
    """
    if "{{" not in text and "\\" not in text:
        return text

    result: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "\\":
                # \\\\ → literal backslash
                result.append("\\")
                i += 2
            elif nxt == "{":
                # \\{ → literal {, prevents expression opening
                result.append("{")
                i += 2
            else:
                result.append(ch)
                i += 1
        elif ch == "{" and i + 1 < n and text[i + 1] == "{":
            # {{ — find closing }} and evaluate
            end = text.find("}}", i + 2)
            if end != -1:
                expr_str = text[i + 2 : end]
                try:
                    val = evaluate(expr_str)
                    result.append(str(val))
                except ExprError:
                    result.append(text[i : end + 2])
                i = end + 2
            else:
                result.append(ch)
                i += 1
        else:
            result.append(ch)
            i += 1
    return "".join(result)
