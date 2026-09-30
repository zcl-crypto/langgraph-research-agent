from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """搜索服务的统一返回结构。"""

    title: str
    url: str
    snippet: str = ""
    content: str | None = None
    score: float | None = Field(default=None, ge=0, le=1)


class WebPageResult(BaseModel):
    """网页正文读取结果。"""

    title: str
    url: str
    content: str


class Source(BaseModel):
    """最终报告引用的来源。"""

    id: str = ""
    title: str
    url: str
    acquisition: Literal["webpage", "search_snippet", "read_failed"] = "webpage"
    relevance_score: float | None = Field(default=None, ge=0, le=1)
    suspicious_content: bool = False


class FindingPoint(BaseModel):
    """带来源编号的单条研究要点。"""

    text: str
    source_ids: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """一个研究任务形成的结论。"""

    task: str
    summary: str
    key_points: list[FindingPoint] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)


class ReviewResult(BaseModel):
    """Reviewer 对现有材料的判断。"""

    sufficient: bool
    reason: str
    missing_information: list[str] = Field(default_factory=list)
    follow_up_query: str | None = None


StreamEventName = Literal[
    "planning",
    "plan_completed",
    "researching",
    "search_completed",
    "reading_webpage",
    "reviewing",
    "retrying",
    "writing",
    "completed",
    "error",
]


class ResearchStreamEvent(BaseModel):
    """LangGraph 节点向 SSE 接口发送的统一事件。"""

    event: StreamEventName
    task_id: str
    stage: str
    message: str
    current_step: int = 0
    total_steps: int = 0
    data: dict[str, Any] = Field(default_factory=dict)
    report: str | None = None
    sources: list[Source] = Field(default_factory=list)
