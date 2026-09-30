import logging

from app.core.exceptions import LLMServiceError
from app.graph.events import emit_graph_event
from app.graph.state import ResearchState
from app.models.llm_outputs import PlanOutput
from app.prompts.planner import PLANNER_SYSTEM_PROMPT
from app.services.llm import LLMClient

logger = logging.getLogger(__name__)


async def planner_node(state: ResearchState, *, llm: LLMClient) -> dict[str, object]:
    """将用户问题拆解为 3～5 个明确研究任务。"""

    logger.info("[task_id=%s] node=planner 开始：生成研究计划", state["task_id"])
    emit_graph_event(
        state,
        event="planning",
        stage="planning",
        message="正在拆解研究问题",
        total_steps=0,
    )
    logger.info("[task_id=%s] node=planner LLM 调用", state["task_id"])
    output = await llm.ainvoke_structured(
        PlanOutput,
        PLANNER_SYSTEM_PROMPT,
        f"用户研究问题：{state['query']}",
    )
    plan = list(dict.fromkeys(task.strip() for task in output.tasks if task.strip()))
    if not 3 <= len(plan) <= 5:
        raise LLMServiceError("Planner 必须生成 3～5 个不重复的有效任务")
    logger.info(
        "[task_id=%s] node=planner 完成：生成 %d 个研究任务",
        state["task_id"],
        len(plan),
    )
    emit_graph_event(
        state,
        event="plan_completed",
        stage="planning",
        message=f"研究计划已生成，共 {len(plan)} 步",
        total_steps=len(plan),
        data={"plan": plan},
    )
    return {
        "plan": plan,
        "current_step": 0,
        "findings": [],
        "sources": [],
        "review_result": None,
        "stage": "researching",
        "errors": [],
        "research_count": 0,
        "retry_count": 0,
        "final_report": "",
    }
