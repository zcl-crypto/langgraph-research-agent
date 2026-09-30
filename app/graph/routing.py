from typing import Literal

from app.graph.state import ResearchState


def route_after_review(state: ResearchState) -> Literal["researcher", "writer"]:
    """信息充分或达到重试上限时进入 writer。"""

    review = state.get("review_result")
    if review and review.sufficient:
        return "writer"
    if state["research_count"] >= state["max_research_loops"]:
        return "writer"
    if state["retry_count"] >= state["max_retries"]:
        return "writer"
    return "researcher"
