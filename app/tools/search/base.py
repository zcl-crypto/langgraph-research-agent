from abc import ABC, abstractmethod

from app.models.research import SearchResult


class SearchProvider(ABC):
    """所有搜索服务实现必须遵循的接口。"""

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """根据关键词返回统一格式的搜索结果。"""
