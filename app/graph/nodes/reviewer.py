import logging
import re

from app.graph.events import emit_graph_event
from app.graph.state import ResearchState
from app.models.llm_outputs import ReviewOutput
from app.models.research import ReviewResult
from app.prompts.reviewer import REVIEWER_SYSTEM_PROMPT
from app.services.llm import LLMClient

logger = logging.getLogger(__name__)
_CHINESE_CHARACTER = re.compile(r"[\u4e00-\u9fff]")


def _ensure_chinese_review(output: ReviewOutput) -> ReviewOutput:
    """兼容偶尔忽略语言要求的模型，保证用户侧审核结论为中文。"""

    if _CHINESE_CHARACTER.search(output.reason):
        return output
    reason = (
        "现有资料已覆盖研究问题和全部计划。"
        if output.sufficient
        else "现有资料仍不足以覆盖研究问题，需要补充检索。"
    )
    missing_information = [
        item if _CHINESE_CHARACTER.search(item) else "需要补充与研究计划相关的关键信息"
        for item in output.missing_information
    ]
    return output.model_copy(
        update={"reason": reason, "missing_information": missing_information}
    )


async def reviewer_node(state: ResearchState, *, llm: LLMClient) -> dict[str, object]:
    """检查计划覆盖度，并决定继续研究还是进入写作。"""

    logger.info(
        "[task_id=%s] node=reviewer 开始：已完成步骤 %d/%d，research 循环 %d/%d",
        state["task_id"],
        min(state["current_step"], len(state["plan"])),
        len(state["plan"]),
        state["research_count"],
        state["max_research_loops"],
    )
    emit_graph_event(
        state,
        event="reviewing",
        stage="reviewing",
        message="正在审核当前研究结果",
        current_step=min(state["current_step"], len(state["plan"])),
    )
    if state["current_step"] < len(state["plan"]):
        next_task = state["plan"][state["current_step"]]
        next_stage = (
            "writing"
            if state["research_count"] >= state["max_research_loops"]
            else "researching"
        )
        reason = "研究计划仍有未执行任务"
        logger.info(
            "[task_id=%s] node=reviewer 完成：计划尚未覆盖，下一阶段=%s",
            state["task_id"],
            next_stage,
        )
        emit_graph_event(
            state,
            event="reviewing",
            stage="reviewing",
            message=reason,
            current_step=state["current_step"],
            data={"sufficient": False, "reason": reason},
        )
        if next_stage == "researching":
            emit_graph_event(
                state,
                event="retrying",
                stage="researching",
                message=f"继续下一项研究：{next_task}",
                current_step=state["current_step"] + 1,
                data={"reason": reason},
            )
        return {
            "review_result": ReviewResult(
                sufficient=False,
                reason=reason,
                missing_information=[next_task],
                follow_up_query=f"{state['query']} {next_task}",
            ),
            "stage": next_stage,
        }

    findings_text = "\n\n".join(
        (
            f"任务：{finding.task}\n摘要：{finding.summary}\n"
            f"要点：{'；'.join(point.text for point in finding.key_points)}"
        )
        for finding in state["findings"]
    )
    logger.info("[task_id=%s] node=reviewer LLM 调用", state["task_id"])
    output = await llm.ainvoke_structured(
        ReviewOutput,
        REVIEWER_SYSTEM_PROMPT,
        (
            f"原始问题：{state['query']}\n"
            f"研究计划：{'；'.join(state['plan'])}\n\n"
            f"现有发现：\n{findings_text}"
        ),
    )
    output = _ensure_chinese_review(output)
    follow_up_query = output.follow_up_query
    if not output.sufficient and not follow_up_query:
        missing = " ".join(output.missing_information) or "补充资料"
        follow_up_query = f"{state['query']} {missing}"
    review_result = ReviewResult(
        sufficient=output.sufficient,
        reason=output.reason,
        missing_information=output.missing_information,
        follow_up_query=follow_up_query,
    )
    retry_count = state["retry_count"] + (0 if output.sufficient else 1)
    should_write = (
        output.sufficient
        or retry_count >= state["max_retries"]
        or state["research_count"] >= state["max_research_loops"]
    )
    next_stage = "writing" if should_write else "researching"
    logger.info(
        "[task_id=%s] node=reviewer 完成：信息充分=%s，Retry=%d/%d，下一阶段=%s",
        state["task_id"],
        output.sufficient,
        retry_count,
        state["max_retries"],
        next_stage,
    )
    emit_graph_event(
        state,
        event="reviewing",
        stage="reviewing",
        message=output.reason,
        current_step=min(state["current_step"], len(state["plan"])),
        data={
            "sufficient": output.sufficient,
            "reason": output.reason,
            "missing_information": output.missing_information,
            "retry_count": retry_count,
        },
    )
    if not output.sufficient and next_stage == "researching":
        emit_graph_event(
            state,
            event="retrying",
            stage="researching",
            message=f"信息不足，准备补充搜索：{output.reason}",
            current_step=len(state["plan"]),
            data={
                "reason": output.reason,
                "follow_up_query": follow_up_query,
                "retry_count": retry_count,
            },
        )
    return {
        "review_result": review_result,
        "retry_count": retry_count,
        "stage": next_stage,
    }
