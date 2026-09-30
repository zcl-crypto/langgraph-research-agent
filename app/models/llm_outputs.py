from pydantic import BaseModel, Field


class PlanOutput(BaseModel):
    """Planner 的结构化输出。"""

    tasks: list[str] = Field(min_length=3, max_length=5)


class FindingPointOutput(BaseModel):
    """Researcher 输出的带证据编号要点。"""

    text: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)


class FindingOutput(BaseModel):
    """Researcher 对网页内容的结构化整理结果。"""

    summary: str = Field(min_length=1)
    key_points: list[FindingPointOutput] = Field(default_factory=list)


class ReviewOutput(BaseModel):
    """Reviewer 的结构化输出。"""

    sufficient: bool
    reason: str
    missing_information: list[str] = Field(default_factory=list)
    follow_up_query: str | None = None


class ReportOutput(BaseModel):
    """扁平 Writer 输出，兼容对嵌套 JSON Schema 支持较弱的模型。"""

    title: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    main_findings: list[str] = Field(min_length=1)
    analysis: list[str] = Field(min_length=1)
    limitations: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)
    citations: dict[str, list[str]] = Field(default_factory=dict)
