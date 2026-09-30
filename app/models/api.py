from pydantic import BaseModel, Field

from app.graph.state import ResearchStage
from app.models.research import Source


class HealthResponse(BaseModel):
    status: str


class ResearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=5_000)


class ResearchResponse(BaseModel):
    task_id: str
    report: str
    sources: list[Source]
    stage: ResearchStage
    token_usage: int = 0
    llm_calls: int = 0
