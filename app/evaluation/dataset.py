import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError


class EvaluationCase(BaseModel):
    """一条离线研究评测问题。"""

    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    query: str = Field(min_length=3)


def load_evaluation_dataset(path: Path) -> list[EvaluationCase]:
    """读取并校验本地 JSON 评测集。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("评测数据集根节点必须是数组")
    try:
        cases = [EvaluationCase.model_validate(item) for item in payload]
    except ValidationError as exc:
        raise ValueError(f"评测数据集格式错误：{exc}") from exc
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("评测数据集中的 id 不能重复")
    return cases
