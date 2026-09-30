import ast
import operator
from collections.abc import Callable

from app.core.exceptions import CalculationError

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def calculate(expression: str) -> int | float:
    """使用 AST 白名单计算基础算术，绝不执行任意 Python 代码。"""

    if not expression.strip() or len(expression) > 200:
        raise CalculationError("算术表达式为空或过长")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculationError("算术表达式格式错误") from exc
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise CalculationError("算术表达式过于复杂")

    def evaluate(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            return _UNARY_OPERATORS[type(node.op)](evaluate(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise CalculationError("指数绝对值不能超过 12")
            try:
                result = _BINARY_OPERATORS[type(node.op)](left, right)
            except (ArithmeticError, OverflowError) as exc:
                raise CalculationError(f"算术运算失败：{exc}") from exc
            if isinstance(result, complex) or abs(result) > 1e15:
                raise CalculationError("计算结果超出允许范围")
            return result
        raise CalculationError("表达式包含不允许的语法")

    return evaluate(tree)
