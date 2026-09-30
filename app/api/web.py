from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

WEB_DIRECTORY = Path(__file__).resolve().parents[1] / "web"
router = APIRouter(include_in_schema=False)


@router.get("/")
async def research_console() -> FileResponse:
    """返回轻量级流式研究演示页面。"""

    return FileResponse(WEB_DIRECTORY / "index.html", media_type="text/html")
