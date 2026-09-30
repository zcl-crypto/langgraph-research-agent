import asyncio
from typing import Any

import pytest

from app.core.exceptions import ResearchTimeoutError
from app.services.research import ResearchService


class SlowGraph:
    """用于验证超时和并发控制的最小 Graph 替身。"""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.active = 0
        self.max_active = 0

    async def ainvoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            return {**state, "stage": "completed"}
        finally:
            self.active -= 1


class SlowStreamingGraph:
    async def astream(self, state: dict[str, Any], **kwargs: Any):
        await asyncio.sleep(0.05)
        yield {
            "event": "planning",
            "task_id": state["task_id"],
            "stage": "planning",
            "message": "延迟事件",
        }


async def test_research_service_enforces_total_timeout() -> None:
    service = ResearchService(
        SlowGraph(0.05),
        max_retries=1,
        research_timeout_seconds=0.01,
    )

    with pytest.raises(ResearchTimeoutError, match="超过"):
        await service.run("验证研究任务超时")


async def test_research_service_limits_concurrent_runs() -> None:
    graph = SlowGraph(0.02)
    service = ResearchService(
        graph,
        max_retries=1,
        max_concurrent_research=1,
    )

    await asyncio.gather(service.run("并发任务一"), service.run("并发任务二"))

    assert graph.max_active == 1


async def test_stream_timeout_is_returned_as_error_event() -> None:
    service = ResearchService(
        SlowStreamingGraph(),
        max_retries=1,
        research_timeout_seconds=0.01,
    )

    events = [event async for event in service.stream("验证流式任务超时")]

    assert events[-1].event == "error"
    assert "超过" in events[-1].message
