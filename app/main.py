import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.research import router
from app.api.web import WEB_DIRECTORY
from app.api.web import router as web_router
from app.core.config import Settings, get_settings
from app.services.research import ResearchService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)


def create_app(
    *,
    settings: Settings | None = None,
    research_service: ResearchService | None = None,
) -> FastAPI:
    """创建 FastAPI 应用，并允许测试注入依赖。"""

    application = FastAPI(
        title="LangGraph Intelligent Research Agent",
        version="0.1.0",
    )
    application.state.settings = settings or get_settings()
    application.state.research_service = research_service
    application.mount("/assets", StaticFiles(directory=WEB_DIRECTORY), name="assets")
    application.include_router(web_router)
    application.include_router(router)
    return application


app = create_app()
