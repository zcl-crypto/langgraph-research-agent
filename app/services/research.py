import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.core.context import TokenUsageTracker, current_task_id, current_token_usage
from app.core.exceptions import ConfigurationError, ResearchAgentError, ResearchTimeoutError
from app.graph.builder import build_research_graph
from app.graph.state import ResearchState
from app.models.research import ResearchStreamEvent, WebPageResult
from app.services.llm import LLMService
from app.tools.search.base import SearchProvider
from app.tools.search.mock import MockSearchProvider
from app.tools.search.tavily import TavilySearchProvider
from app.tools.webpage import read_webpage

logger = logging.getLogger(__name__)


class ResearchService:
    """为 API 提供一次完整的 LangGraph 研究执行。"""

    def __init__(
        self,
        graph: Any,
        max_retries: int,
        max_research_loops: int = 8,
        *,
        max_concurrent_research: int = 2,
        research_timeout_seconds: float = 300.0,
        research_task_token_limit: int = 200_000,
    ) -> None:
        self._graph = graph
        self._max_retries = max_retries
        self._max_research_loops = max_research_loops
        self._semaphore = asyncio.Semaphore(max_concurrent_research)
        self._research_timeout_seconds = research_timeout_seconds
        self._research_task_token_limit = research_task_token_limit

    async def run(self, query: str) -> ResearchState:
        """创建初始状态并运行到 END。"""

        task_id = uuid4().hex
        initial_state = self._create_initial_state(query, task_id)
        usage_tracker = TokenUsageTracker(limit=self._research_task_token_limit)
        logger.info("[task_id=%s] research 流程开始", task_id)
        try:
            async with self._semaphore:
                token = current_task_id.set(task_id)
                usage_token = current_token_usage.set(usage_tracker)
                try:
                    async with asyncio.timeout(self._research_timeout_seconds):
                        result = await self._graph.ainvoke(
                            initial_state,
                            config={"recursion_limit": 50},
                        )
                finally:
                    current_token_usage.reset(usage_token)
                    current_task_id.reset(token)
        except TimeoutError as exc:
            logger.error(
                "[task_id=%s] research 流程结束：final_status=timeout timeout_seconds=%.1f",
                task_id,
                self._research_timeout_seconds,
            )
            raise ResearchTimeoutError(
                f"研究任务超过 {self._research_timeout_seconds:g} 秒限制"
            ) from exc
        except Exception as exc:
            logger.error(
                "[task_id=%s] research 流程结束：final_status=failed type=%s",
                task_id,
                type(exc).__name__,
            )
            raise
        result["token_usage"] = usage_tracker.total_tokens
        result["llm_calls"] = usage_tracker.call_count
        logger.info(
            "[task_id=%s] research 流程完成：final_status=%s，findings=%d，sources=%d",
            task_id,
            result["stage"],
            len(result["findings"]),
            len(result["sources"]),
        )
        return result

    async def stream(self, query: str) -> AsyncGenerator[ResearchStreamEvent, None]:
        """直接转发 LangGraph custom stream，并将异常转换为 error 事件。"""

        task_id = uuid4().hex
        initial_state = self._create_initial_state(query, task_id)
        usage_tracker = TokenUsageTracker(limit=self._research_task_token_limit)
        logger.info("[task_id=%s] stream research 流程开始", task_id)
        async with self._semaphore:
            graph_stream = self._graph.astream(
                initial_state,
                config={"recursion_limit": 50},
                stream_mode="custom",
            )
            try:
                async with asyncio.timeout(self._research_timeout_seconds):
                    while True:
                        # ContextVar 不跨越 yield，避免流在其他异步上下文关闭时 reset 失败。
                        token = current_task_id.set(task_id)
                        usage_token = current_token_usage.set(usage_tracker)
                        try:
                            chunk = await anext(graph_stream)
                        except StopAsyncIteration:
                            break
                        finally:
                            current_token_usage.reset(usage_token)
                            current_task_id.reset(token)
                        yield ResearchStreamEvent.model_validate(chunk)
                logger.info(
                    (
                        "[task_id=%s] stream research 流程完成：final_status=completed "
                        "total_tokens=%d"
                    ),
                    task_id,
                    usage_tracker.total_tokens,
                )
            except TimeoutError:
                logger.error(
                    "[task_id=%s] stream research 结束：final_status=timeout",
                    task_id,
                )
                yield ResearchStreamEvent(
                    event="error",
                    task_id=task_id,
                    stage="error",
                    message=f"研究任务超过 {self._research_timeout_seconds:g} 秒限制",
                )
            except asyncio.CancelledError:
                logger.info("[task_id=%s] SSE 客户端断开", task_id)
                raise
            except Exception as exc:
                logger.error(
                    "[task_id=%s] stream research 结束：final_status=failed type=%s",
                    task_id,
                    type(exc).__name__,
                )
                message = (
                    str(exc) if isinstance(exc, ResearchAgentError) else "研究流程执行失败"
                )
                yield ResearchStreamEvent(
                    event="error",
                    task_id=task_id,
                    stage="error",
                    message=message,
                )
            finally:
                # 显式关闭底层 LangGraph 流，确保客户端断开时释放任务与网络资源。
                await graph_stream.aclose()

    def _create_initial_state(self, query: str, task_id: str) -> ResearchState:
        """为同步和流式执行创建一致的初始状态。"""

        return {
            "query": query,
            "task_id": task_id,
            "plan": [],
            "current_step": 0,
            "findings": [],
            "sources": [],
            "review_result": None,
            "stage": "planning",
            "errors": [],
            "research_count": 0,
            "max_research_loops": self._max_research_loops,
            "retry_count": 0,
            "max_retries": self._max_retries,
            "content_filter_count": 0,
            "content_filter_recovered_count": 0,
            "defensive_retry_count": 0,
            "suspicious_sources_excluded": 0,
            "token_usage": 0,
            "llm_calls": 0,
            "final_report": "",
        }


def _create_search_provider(settings: Settings) -> SearchProvider:
    """根据配置选择搜索实现，业务节点无需感知供应商。"""

    if settings.search_provider == "mock":
        return MockSearchProvider()
    api_key = settings.search_api_key.get_secret_value()
    if not api_key:
        raise ConfigurationError("SEARCH_PROVIDER=tavily 时必须配置 SEARCH_API_KEY")
    return TavilySearchProvider(
        api_key=api_key,
        api_url=settings.search_api_url,
        timeout=settings.webpage_timeout_seconds,
        include_raw_content=settings.search_include_raw_content,
        include_domains=settings.included_search_domains,
        exclude_domains=settings.excluded_search_domains,
    )


def build_research_service(settings: Settings) -> ResearchService:
    """使用生产配置创建 ResearchService。"""

    llm = LLMService(settings)
    search_provider = _create_search_provider(settings)

    async def configured_page_reader(url: str) -> WebPageResult:
        return await read_webpage(
            url,
            timeout=settings.webpage_timeout_seconds,
            max_chars=settings.webpage_max_chars,
        )

    graph = build_research_graph(
        llm=llm,
        search_provider=search_provider,
        page_reader=configured_page_reader,
        settings=settings,
    )
    return ResearchService(
        graph,
        max_retries=settings.max_research_retries,
        max_research_loops=settings.max_research_loops,
        max_concurrent_research=settings.max_concurrent_research,
        research_timeout_seconds=settings.research_timeout_seconds,
        research_task_token_limit=settings.research_task_token_limit,
    )
