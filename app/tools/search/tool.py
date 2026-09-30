import logging
from time import perf_counter

from app.core.context import get_current_task_id
from app.core.exceptions import SearchError
from app.models.research import SearchResult
from app.tools.search.base import SearchProvider

logger = logging.getLogger(__name__)


async def search_web(
    query: str,
    provider: SearchProvider,
    limit: int = 5,
) -> list[SearchResult]:
    """调用可替换搜索服务，并统一处理工具异常。"""

    cleaned_query = query.strip()
    if not cleaned_query:
        raise SearchError("搜索关键词不能为空")
    started_at = perf_counter()
    task_id = get_current_task_id()
    provider_name = type(provider).__name__
    logger.info(
        "[task_id=%s] tool=search_web 开始：provider=%s",
        task_id,
        provider_name,
    )
    try:
        results = await provider.search(cleaned_query, limit=limit)
    except SearchError:
        logger.error(
            "[task_id=%s] tool=search_web 失败：provider=%s duration_ms=%.1f",
            task_id,
            provider_name,
            (perf_counter() - started_at) * 1000,
        )
        raise
    except Exception as exc:
        logger.error(
            "[task_id=%s] tool=search_web 失败：provider=%s duration_ms=%.1f type=%s",
            task_id,
            provider_name,
            (perf_counter() - started_at) * 1000,
            type(exc).__name__,
        )
        raise SearchError(f"搜索工具执行失败：{exc}") from exc
    logger.info(
        "[task_id=%s] tool=search_web 完成：provider=%s duration_ms=%.1f results=%d",
        task_id,
        provider_name,
        (perf_counter() - started_at) * 1000,
        len(results),
    )
    return results
