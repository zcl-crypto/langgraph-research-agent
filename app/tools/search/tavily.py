import httpx

from app.core.exceptions import SearchError
from app.models.research import SearchResult
from app.tools.search.base import SearchProvider


class TavilySearchProvider(SearchProvider):
    """通过 Tavily HTTP API 实现真实网页搜索。"""

    def __init__(
        self,
        api_key: str,
        api_url: str,
        timeout: float = 15.0,
        *,
        include_raw_content: bool = True,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_url = api_url
        self._timeout = timeout
        self._include_raw_content = include_raw_content
        self._include_domains = include_domains or []
        self._exclude_domains = exclude_domains or []

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._api_url,
                    json={
                        "api_key": self._api_key,
                        "query": query,
                        "max_results": limit,
                        "search_depth": "basic",
                        "include_raw_content": self._include_raw_content,
                        "include_domains": self._include_domains,
                        "exclude_domains": self._exclude_domains,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchError(f"搜索服务调用失败：{exc}") from exc

        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise SearchError("搜索服务返回了无法识别的数据结构")

        results: list[SearchResult] = []
        for item in raw_results[:limit]:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            score_value = item.get("score")
            score = (
                max(0.0, min(float(score_value), 1.0))
                if isinstance(score_value, int | float)
                else None
            )
            raw_content = item.get("raw_content")
            results.append(
                SearchResult(
                    title=str(item.get("title") or item["url"]),
                    url=str(item["url"]),
                    snippet=str(item.get("content") or ""),
                    content=str(raw_content) if raw_content else None,
                    score=score,
                )
            )
        return results
