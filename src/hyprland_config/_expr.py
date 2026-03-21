"""Expression evaluator for Hyprland {{expr}} syntax.

Supports integer and float arithmetic: +, -, *, /, %, parentheses.
Variable references ($var) should be expanded before evaluation.
"""

import re

# Tokenizer: numbers (int/float), operators, parentheses, whitespace
_TOKEN_RE = re.compile(
    r"\s*(?:"
    r"(\d+(?:\.\d+)?)"  # number
    r"|([+\-*/%()])"  # operator or paren
    r")\s*"
)


class ExprError(Exception):
    """Raised when an expression cannot be evaluated."""


def _tokenize(expr: str) -> list[tuple[str, str]]:
    """Tokenize an expression into (type, value) pairs.

    Types: 'num', 'op'
    """
    tokens: list[tuple[str, str]] = []
    pos = 0
    expr = expr.strip()
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m or m.start() != pos:
            raise ExprError(f"unexpected character in expression: {expr[pos:]!r}")
        if m.group(1) is not None:
            tokens.append(("num", m.group(1)))
        elif m.group(2) is not None:
            tokens.append(("op", m.group(2)))
        pos = m.end()
    return tokens


def _parse_expr(tokens: list[tuple[str, str]], pos: int) -> tuple[float, int]:
    """Parse additive expression: term ((+|-) term)*."""
    left, pos = _parse_term(tokens, pos)
    while pos < len(tokens) and tokens[pos][0] == "op" and tokens[pos][1] in "+-":
        op = tokens[pos][1]
        pos += 1
        right, pos = _parse_term(tokens, pos)
        if op == "+":
            left += right
        else:
            left -= right
    return left, pos


def _parse_term(tokens: list[tuple[str, str]], pos: int) -> tuple[float, int]:
    """Parse multiplicative expression: unary ((*|/|%) unary)*."""
    left, pos = _parse_unary(tokens, pos)
    while pos < len(tokens) and tokens[pos][0] == "op" and tokens[pos][1] in "*/%":
        op = tokens[pos][1]
        pos += 1
        right, pos = _parse_unary(tokens, pos)
        if op == "*":
            left *= right
        elif op == "/":
            if right == 0:
                raise ExprError("division by zero")
            left /= right
        else:
            if right == 0:
                raise ExprError("modulo by zero")
            left %= right
    return left, pos


def _parse_unary(tokens: list[tuple[str, str]], pos: int) -> tuple[float, int]:
    """Parse unary +/- prefix or primary."""
    if pos < len(tokens) and tokens[pos] == ("op", "-"):
        pos += 1
        val, pos = _parse_unary(tokens, pos)
        return -val, pos
    if pos < len(tokens) and tokens[pos] == ("op", "+"):
        pos += 1
        return _parse_unary(tokens, pos)
    return _parse_primary(tokens, pos)


def _parse_primary(tokens: list[tuple[str, str]], pos: int) -> tuple[float, int]:
    """Parse number or parenthesised expression."""
    if pos >= len(tokens):
        raise ExprError("unexpected end of expression")
    tok_type, tok_val = tokens[pos]
    if tok_type == "num":
        return float(tok_val), pos + 1
    if tok_val == "(":
        pos += 1
        val, pos = _parse_expr(tokens, pos)
        if pos >= len(tokens) or tokens[pos] != ("op", ")"):
            raise ExprError("missing closing parenthesis")
        return val, pos + 1
    raise ExprError(f"unexpected token: {tok_val!r}")


def evaluate(expr: str) -> int | float:
    """Evaluate a simple arithmetic expression.

    Returns int when the result is a whole number, float otherwise.
    """
    tokens = _tokenize(expr)
    if not tokens:
        raise ExprError("empty expression")
    result, pos = _parse_expr(tokens, 0)
    if pos != len(tokens):
        raise ExprError(f"unexpected token after expression: {tokens[pos][1]!r}")
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
