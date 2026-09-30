"""使用真实 LLM 和搜索服务运行一次完整研究流程。"""

import argparse
import asyncio
import logging
import sys

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.models.research import ResearchStreamEvent
from app.services.research import build_research_service

DEFAULT_QUERY = (
    "分析当前 AI Agent 在企业应用中的主要落地方向，"
    "包括典型应用场景、主要技术架构和目前存在的挑战。"
)


def configure_console() -> None:
    """强制使用 UTF-8 输出，避免 Windows GBK 无法打印网页特殊字符。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _print_event(event: ResearchStreamEvent) -> None:
    """将 SSE 同源事件转换为便于人工检查的终端输出。"""

    prefix = f"[{event.event}]"
    print(f"\n{prefix} {event.message}")

    if event.event == "plan_completed":
        plan = event.data.get("plan", [])
        print("\nPlanner 研究计划：")
        for index, task in enumerate(plan, start=1):
            print(f"  {index}. {task}")
    elif event.event == "search_completed":
        results = event.data.get("results", [])
        print("搜索结果：")
        for result in results:
            if isinstance(result, dict):
                print(f"  - {result.get('title', '无标题')}")
                print(f"    URL: {result.get('url', '')}")
                snippet = str(result.get("snippet", "")).strip()
                if snippet:
                    print(f"    摘要: {snippet}")
    elif event.event == "reviewing" and "sufficient" in event.data:
        sufficient = event.data.get("sufficient")
        print(f"Reviewer 判断：{'信息充足' if sufficient else '信息不足'}")
        print(f"原因：{event.data.get('reason', event.message)}")
    elif event.event == "retrying":
        print(f"补充搜索原因：{event.data.get('reason', event.message)}")
    elif event.event == "completed":
        print("\n========== 最终 Markdown 报告 ==========\n")
        print(event.report or "")
        print("\n========== 引用来源 URL ==========\n")
        for source in event.sources:
            print(source.url)


async def run_demo(query: str) -> int:
    """校验真实配置并消费完整 LangGraph 事件流。"""

    settings = Settings()
    if not settings.api_key.get_secret_value():
        raise ConfigurationError("缺少 LLM_API_KEY，请先配置 .env")
    if settings.search_provider == "mock":
        raise ConfigurationError(
            "真实 Demo 不允许使用 MockSearchProvider，请设置 SEARCH_PROVIDER=tavily"
        )
    if not settings.search_api_key.get_secret_value():
        raise ConfigurationError("缺少 SEARCH_API_KEY，请先配置真实搜索服务")

    service = build_research_service(settings)
    async for event in service.stream(query):
        _print_event(event)
        if event.event == "error":
            return 1
    return 0


def main() -> int:
    """解析命令行参数并运行异步研究任务。"""

    configure_console()
    parser = argparse.ArgumentParser(description="运行真实 LangGraph 研究 Agent Demo")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="要研究的问题")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    try:
        return asyncio.run(run_demo(args.query))
    except ConfigurationError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
