import pytest

from app.core.exceptions import CalculationError
from app.tools.calculator import calculate


def test_calculate_supports_basic_arithmetic() -> None:
    assert calculate("(12 + 8) * 3 / 2") == 30


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('dir')",
        "open('secret.txt')",
        "value + 1",
        "(1).__class__",
        "2 ** 100",
    ],
)
def test_calculate_rejects_unsafe_expressions(expression: str) -> None:
    with pytest.raises(CalculationError):
        calculate(expression)
