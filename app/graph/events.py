from typing import Any

from langgraph.config import get_stream_writer

from app.graph.state import ResearchState
from app.models.research import ResearchStreamEvent, Source, StreamEventName


def emit_graph_event(
    state: ResearchState,
    *,
    event: StreamEventName,
    stage: str,
    message: str,
    current_step: int = 0,
    total_steps: int | None = None,
    data: dict[str, Any] | None = None,
    report: str | None = None,
    sources: list[Source] | None = None,
) -> None:
    """通过 LangGraph 原生 custom stream 发出结构化进度事件。"""

    payload = ResearchStreamEvent(
        event=event,
        task_id=state["task_id"],
        stage=stage,
        message=message,
        current_step=current_step,
        total_steps=len(state["plan"]) if total_steps is None else total_steps,
        data=data or {},
        report=report,
        sources=sources or [],
    )
    try:
        writer = get_stream_writer()
    except RuntimeError:
        # 节点单元测试可脱离 LangGraph 运行，此时没有 stream writer。
        return
    writer(payload.model_dump(mode="json"))
