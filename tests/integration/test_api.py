import asyncio
import json
from typing import TypeVar

from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr

from app.core.config import Settings
from app.core.exceptions import LLMServiceError
from app.graph.builder import build_research_graph
from app.main import create_app
from app.models.llm_outputs import FindingOutput, PlanOutput, ReportOutput, ReviewOutput
from app.models.research import WebPageResult
from app.services.research import ResearchService
from app.tools.search.mock import MockSearchProvider

ModelT = TypeVar("ModelT", bound=BaseModel)


class FakeLLM:
    """让集成测试不依赖外部模型服务。"""

    async def ainvoke_text(self, system_prompt: str, user_prompt: str) -> str:
        return (
            "# LangGraph 研究报告\n\n"
            "## 执行摘要\n\n测试流程已收集并整理多个研究任务的资料。\n\n"
            "## 主要发现\n\n研究状态能够在节点之间正确传递。\n\n"
            "## 综合分析\n\n规划、搜索、审核与写作形成闭环。\n\n"
            "## 局限性\n\n当前使用本地模拟搜索资料。\n\n"
            "## 结论\n\nMVP 完整流程可以运行。"
        )

    async def ainvoke_structured(
        self,
        schema: type[ModelT],
        system_prompt: str,
        user_prompt: str,
    ) -> ModelT:
        if schema is PlanOutput:
            payload: dict[str, object] = {
                "tasks": [
                    "梳理核心概念和背景",
                    "分析关键实现机制",
                    "总结限制与适用场景",
                ]
            }
        elif schema is FindingOutput:
            payload = {
                "summary": "资料支持当前研究任务的基本结论。",
                "key_points": [
                    {"text": "状态清晰", "source_ids": ["S1"]},
                    {"text": "来源可追溯", "source_ids": ["S1", "S2"]},
                ],
            }
        elif schema is ReviewOutput:
            payload = {
                "sufficient": True,
                "reason": "所有计划任务均已有对应资料",
                "missing_information": [],
            }
        elif schema is ReportOutput:
            payload = {
                "title": "LangGraph 研究报告",
                "executive_summary": "测试流程已收集并整理多个研究任务的资料。",
                "main_findings": ["研究状态能够在节点之间正确传递。"],
                "analysis": ["规划、搜索、审核与写作形成闭环。"],
                "limitations": "当前使用本地模拟搜索资料。",
                "conclusion": "MVP 完整流程可以运行。",
                "citations": {
                    "executive_summary": ["S1"],
                    "main_findings_1": ["S1", "S2"],
                    "analysis_1": ["S1"],
                    "conclusion": ["S1"],
                },
            }
        else:
            raise AssertionError(f"未处理的结构化模型：{schema}")
        return schema.model_validate(payload)


class AlwaysInsufficientLLM(FakeLLM):
    """模拟 Reviewer 持续要求补充资料。"""

    async def ainvoke_structured(
        self,
        schema: type[ModelT],
        system_prompt: str,
        user_prompt: str,
    ) -> ModelT:
        if schema is ReviewOutput:
            return schema.model_validate(
                {
                    "sufficient": False,
                    "reason": "仍缺少对照资料",
                    "missing_information": ["补充对照资料"],
                    "follow_up_query": "LangGraph 研究流程 对照资料",
                }
            )
        return await super().ainvoke_structured(schema, system_prompt, user_prompt)


class FailingLLM(FakeLLM):
    """模拟模型在 Planner 阶段失败。"""

    async def ainvoke_structured(
        self,
        schema: type[ModelT],
        system_prompt: str,
        user_prompt: str,
    ) -> ModelT:
        raise LLMServiceError("测试模型不可用")


async def unused_page_reader(url: str) -> WebPageResult:
    raise AssertionError(f"Mock 搜索结果自带正文，不应读取网络：{url}")


def build_test_service(
    llm: FakeLLM | None = None,
    *,
    max_retries: int = 2,
    max_research_loops: int = 8,
) -> ResearchService:
    settings = Settings(
        search_provider="mock",
        max_research_retries=max_retries,
        max_research_loops=max_research_loops,
        search_results_limit=2,
        max_pages_per_step=2,
    )
    graph = build_research_graph(
        llm=llm or FakeLLM(),
        search_provider=MockSearchProvider(),
        page_reader=unused_page_reader,
        settings=settings,
    )
    return ResearchService(
        graph,
        max_retries=settings.max_research_retries,
        max_research_loops=settings.max_research_loops,
    )


def test_health_endpoint() -> None:
    app = create_app(settings=Settings())
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_demo_page_and_assets_are_available() -> None:
    app = create_app(settings=Settings())
    with TestClient(app) as client:
        page_response = client.get("/")
        script_response = client.get("/assets/app.js")

    assert page_response.status_code == 200
    assert "Research Agent Console" in page_response.text
    assert script_response.status_code == 200
    assert "/research/stream" in script_response.text


def test_complete_research_flow() -> None:
    app = create_app(
        settings=Settings(),
        research_service=build_test_service(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/research",
            json={"query": "LangGraph 如何管理可循环的研究工作流？"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"]
    assert payload["report"].startswith("# LangGraph 研究报告")
    assert "## 参考来源" in payload["report"]
    assert payload["stage"] == "completed"
    assert payload["token_usage"] == 0
    assert payload["llm_calls"] == 0
    assert len(payload["sources"]) >= 3
    assert len({source["url"] for source in payload["sources"]}) == len(payload["sources"])
    assert all(source["url"].startswith("https://") for source in payload["sources"])


def _parse_sse_events(body: str) -> list[dict[str, object]]:
    """解析测试客户端收集到的 SSE 响应。"""

    events: list[dict[str, object]] = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event_name = next(
            line.removeprefix("event: ")
            for line in lines
            if line.startswith("event: ")
        )
        data_text = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        data = json.loads(data_text)
        assert data["event"] == event_name
        events.append(data)
    return events


def test_stream_returns_structured_events_in_basic_stage_order() -> None:
    app = create_app(
        settings=Settings(),
        research_service=build_test_service(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/research/stream",
            json={"query": "LangGraph 如何流式返回研究进度？"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_events(response.text)
    event_names = [str(event["event"]) for event in events]
    required = [
        "planning",
        "plan_completed",
        "researching",
        "search_completed",
        "reading_webpage",
        "reviewing",
        "writing",
        "completed",
    ]
    positions = [event_names.index(name) for name in required]

    assert positions == sorted(positions)
    assert all(
        {"event", "task_id", "stage", "message", "current_step", "total_steps"}
        <= event.keys()
        for event in events
    )
    completed = next(event for event in events if event["event"] == "completed")
    assert completed["report"]
    assert completed["sources"]


def test_stream_returns_error_event_when_graph_fails() -> None:
    app = create_app(
        settings=Settings(),
        research_service=build_test_service(FailingLLM()),
    )
    with TestClient(app) as client:
        response = client.post(
            "/research/stream",
            json={"query": "触发测试模型错误"},
        )

    events = _parse_sse_events(response.text)

    assert response.status_code == 200
    assert events[-1]["event"] == "error"
    assert events[-1]["stage"] == "error"


async def test_stream_can_be_closed_from_another_async_context() -> None:
    """客户端提前断开时，不应因 ContextVar token 所属上下文不同而报错。"""

    stream = build_test_service().stream("验证流式连接提前关闭")

    first_event = await anext(stream)
    await asyncio.create_task(stream.aclose())

    assert first_event.event == "planning"


async def test_research_stops_at_retry_limit() -> None:
    service = build_test_service(AlwaysInsufficientLLM(), max_retries=2)

    state = await service.run("如何验证研究 Agent 的循环终止机制？")

    assert state["retry_count"] == 2
    assert state["review_result"] is not None
    assert state["review_result"].sufficient is False
    assert "## 参考来源" in state["final_report"]


async def test_research_stops_at_total_loop_limit() -> None:
    service = build_test_service(
        AlwaysInsufficientLLM(),
        max_retries=10,
        max_research_loops=1,
    )

    state = await service.run("如何限制研究 Agent 的总循环次数？")

    assert state["research_count"] == 1
    assert state["current_step"] < len(state["plan"])
    assert state["stage"] == "completed"
    assert state["final_report"]


def test_research_requires_model_key_without_injected_service() -> None:
    app = create_app(settings=Settings(api_key=SecretStr("")))
    with TestClient(app) as client:
        response = client.post("/research", json={"query": "测试模型配置错误"})

    assert response.status_code == 503
    assert "LLM_API_KEY" in response.json()["detail"]
