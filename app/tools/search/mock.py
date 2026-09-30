import hashlib

from app.models.research import SearchResult
from app.tools.search.base import SearchProvider


class MockSearchProvider(SearchProvider):
    """无搜索密钥时用于本地演示和测试的独立实现。"""

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
        results: list[SearchResult] = []
        for index in range(min(limit, 3)):
            results.append(
                SearchResult(
                    title=f"本地模拟资料 {index + 1}",
                    url=f"https://example.com/mock-research/{digest}/{index + 1}",
                    snippet=f"围绕“{query}”的模拟搜索摘要。",
                    content=(
                        f"这是一段用于本地流程验证的模拟资料，主题是：{query}。"
                        "它只用于验证规划、研究、审核和写作链路，不能作为真实研究结论。"
                    ),
                    score=1.0,
                )
            )
        return results
