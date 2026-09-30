from typing import Literal, TypedDict

from app.models.research import Finding, ReviewResult, Source

ResearchStage = Literal[
    "planning",
    "researching",
    "reviewing",
    "writing",
    "completed",
]


class ResearchState(TypedDict):
    """LangGraph 节点之间共享的研究状态。"""

    query: str
    task_id: str
    plan: list[str]
    current_step: int
    findings: list[Finding]
    sources: list[Source]
    review_result: ReviewResult | None
    stage: ResearchStage
    errors: list[str]
    research_count: int
    max_research_loops: int
    retry_count: int
    max_retries: int
    content_filter_count: int
    content_filter_recovered_count: int
    defensive_retry_count: int
    suspicious_sources_excluded: int
    token_usage: int
    llm_calls: int
    final_report: str
