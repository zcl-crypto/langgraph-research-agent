import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.core.exceptions import ConfigurationError, ResearchAgentError, ResearchTimeoutError
from app.models.api import HealthResponse, ResearchRequest, ResearchResponse
from app.models.research import ResearchStreamEvent
from app.services.research import ResearchService, build_research_service

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_research_service(request: Request) -> ResearchService:
    """延迟创建服务，使 health 在未配置模型密钥时仍可用。"""

    service = request.app.state.research_service
    if service is None:
        service = build_research_service(request.app.state.settings)
        request.app.state.research_service = service
    return service


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """返回服务存活状态。"""

    return HealthResponse(status="ok")


@router.post("/research", response_model=ResearchResponse)
async def research(payload: ResearchRequest, request: Request) -> ResearchResponse:
    """执行完整研究工作流并返回报告和来源。"""

    try:
        service = _get_research_service(request)
        state = await service.run(payload.query.strip())
        return ResearchResponse(
            task_id=state["task_id"],
            report=state["final_report"],
            sources=state["sources"],
            stage=state["stage"],
            token_usage=state["token_usage"],
            llm_calls=state["llm_calls"],
        )
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ResearchTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        ) from exc
    except ResearchAgentError as exc:
        logger.warning("研究流程执行失败：%s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("研究流程发生未预期错误")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="研究流程执行失败",
        ) from exc


def _format_sse(event: ResearchStreamEvent) -> str:
    """将研究事件编码为标准 SSE 消息。"""

    return f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"


@router.post("/research/stream")
async def research_stream(payload: ResearchRequest, request: Request) -> StreamingResponse:
    """使用 SSE 实时返回 LangGraph 节点和工具执行进度。"""

    async def event_generator() -> AsyncIterator[str]:
        try:
            service = _get_research_service(request)
            async for event in service.stream(payload.query.strip()):
                yield _format_sse(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("创建流式研究任务失败：type=%s", type(exc).__name__)
            message = str(exc) if isinstance(exc, ResearchAgentError) else "研究流程执行失败"
            yield _format_sse(
                ResearchStreamEvent(
                    event="error",
                    task_id="unavailable",
                    stage="error",
                    message=message,
                )
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
