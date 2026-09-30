import json
import logging
import re
from urllib.parse import urlsplit, urlunsplit

from app.core.context import get_current_token_usage
from app.graph.events import emit_graph_event
from app.graph.state import ResearchState
from app.models.llm_outputs import ReportOutput
from app.models.research import Source
from app.prompts.writer import WRITER_SYSTEM_PROMPT
from app.services.llm import LLMClient

logger = logging.getLogger(__name__)
_CITATION_PATTERN = re.compile(r"\s*\[S\d+\]")
_ACQUISITION_LABELS = {
    "webpage": "网页正文",
    "search_snippet": "搜索摘要",
    "read_failed": "读取失败",
}


def _normalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            parsed.query,
            "",
        )
    )


def _clean_markdown_text(text: str) -> str:
    """移除模型可能夹带的代码围栏和来源编号，由程序重新渲染。"""

    cleaned = text.replace("```markdown", "").replace("```", "").strip()
    return _CITATION_PATTERN.sub("", cleaned).strip()


def _render_cited_text(
    text: str,
    source_ids: list[str],
    *,
    valid_source_ids: set[str],
    fallback_source_ids: list[str],
    citations_required: bool = True,
) -> str:
    """只渲染真实存在的来源编号，并为事实段落提供安全回退。"""

    source_ids = list(
        dict.fromkeys(
            source_id for source_id in source_ids if source_id in valid_source_ids
        )
    )
    if citations_required and not source_ids:
        source_ids = fallback_source_ids
    citations = "".join(f"[{source_id}]" for source_id in source_ids)
    return f"{_clean_markdown_text(text)} {citations}".rstrip()


def _unique_citable_sources(sources: list[Source]) -> list[Source]:
    """过滤不可引用来源并按规范化 URL 去重。"""

    unique: list[Source] = []
    known_urls: set[str] = set()
    for source in sources:
        normalized = _normalize_url(source.url)
        if source.acquisition == "read_failed" or normalized in known_urls:
            continue
        unique.append(source)
        known_urls.add(normalized)
    return unique


def _render_report(output: ReportOutput, sources: list[Source]) -> str:
    """把结构化 Writer 输出确定性渲染为单一 Markdown 报告。"""

    valid_source_ids = {source.id for source in sources}
    fallback_source_ids = [source.id for source in sources[:3]]
    title = _clean_markdown_text(output.title).lstrip("# ") or "研究报告"
    parts = [
        f"# {title}",
        "## 执行摘要",
        _render_cited_text(
            output.executive_summary,
            output.citations.get("executive_summary", []),
            valid_source_ids=valid_source_ids,
            fallback_source_ids=fallback_source_ids,
        ),
        "## 主要发现",
    ]
    parts.append(
        "\n".join(
            "- "
            + _render_cited_text(
                finding,
                output.citations.get(f"main_findings_{index}", []),
                valid_source_ids=valid_source_ids,
                fallback_source_ids=fallback_source_ids,
            )
            for index, finding in enumerate(output.main_findings, start=1)
        )
    )
    parts.extend(
        [
            "## 综合分析",
            "\n\n".join(
                _render_cited_text(
                    paragraph,
                    output.citations.get(f"analysis_{index}", []),
                    valid_source_ids=valid_source_ids,
                    fallback_source_ids=fallback_source_ids,
                )
                for index, paragraph in enumerate(output.analysis, start=1)
            ),
        ]
    )
    parts.extend(
        [
            "## 局限性",
            _render_cited_text(
                output.limitations,
                output.citations.get("limitations", []),
                valid_source_ids=valid_source_ids,
                fallback_source_ids=[],
                citations_required=False,
            ),
            "## 结论",
            _render_cited_text(
                output.conclusion,
                output.citations.get("conclusion", []),
                valid_source_ids=valid_source_ids,
                fallback_source_ids=fallback_source_ids,
            ),
            "## 参考来源",
        ]
    )
    if sources:
        references: list[str] = []
        for source in sources:
            safe_title = source.title.replace("[", "（").replace("]", "）")
            metadata = _ACQUISITION_LABELS[source.acquisition]
            if source.relevance_score is not None:
                metadata += f"，相关性 {source.relevance_score:.2f}"
            if source.suspicious_content:
                metadata += "，已按不可信内容隔离"
            references.append(f"- [{source.id}] [{safe_title}]({source.url})（{metadata}）")
        parts.append("\n".join(references))
    else:
        parts.append("- 暂无可用来源")
    return "\n\n".join(parts).rstrip() + "\n"


async def writer_node(state: ResearchState, *, llm: LLMClient) -> dict[str, object]:
    """依据带证据编号的发现生成结构化报告，再确定性渲染 Markdown。"""

    unique_sources = _unique_citable_sources(state["sources"])
    logger.info(
        "[task_id=%s] node=writer 开始：使用 %d 条 finding 和 %d 个来源",
        state["task_id"],
        len(state["findings"]),
        len(unique_sources),
    )
    emit_graph_event(
        state,
        event="writing",
        stage="writing",
        message="正在生成 Markdown 研究报告",
        current_step=len(state["plan"]),
    )
    evidence_payload = {
        "findings": [finding.model_dump(mode="json") for finding in state["findings"]],
        "sources": [source.model_dump(mode="json") for source in unique_sources],
    }
    review = state["review_result"]
    review_note = review.reason if review else "未提供"
    errors_text = "；".join(state["errors"]) if state["errors"] else "无"
    logger.info("[task_id=%s] node=writer LLM 调用", state["task_id"])
    output = await llm.ainvoke_structured(
        ReportOutput,
        WRITER_SYSTEM_PROMPT,
        (
            f"原始问题：{state['query']}\n"
            f"Reviewer 结论：{review_note}\n"
            f"工具异常记录：{errors_text}\n\n"
            "以下 JSON 是唯一允许使用的研究证据：\n"
            f"{json.dumps(evidence_payload, ensure_ascii=False)}"
        ),
    )
    final_report = _render_report(output, unique_sources)
    logger.info(
        "[task_id=%s] node=writer 完成：报告长度 %d 字符，最终状态=completed",
        state["task_id"],
        len(final_report),
    )
    usage_tracker = get_current_token_usage()
    emit_graph_event(
        state,
        event="completed",
        stage="completed",
        message="研究报告生成完成",
        current_step=len(state["plan"]),
        report=final_report,
        sources=unique_sources,
        data={
            "token_usage": usage_tracker.total_tokens if usage_tracker else 0,
            "llm_calls": usage_tracker.call_count if usage_tracker else 0,
        },
    )
    return {"final_report": final_report, "sources": unique_sources, "stage": "completed"}
