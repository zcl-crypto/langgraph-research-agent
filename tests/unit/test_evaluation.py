from app.evaluation.metrics import evaluate_research_state, summarize_evaluations
from app.graph.state import ResearchState
from app.models.research import Finding, FindingPoint, Source


def make_evaluation_state() -> ResearchState:
    """创建包含真实引用关系的评测状态。"""

    return {
        "query": "研究 LangGraph 状态管理",
        "task_id": "evaluation-task",
        "plan": ["状态管理", "条件路由"],
        "current_step": 2,
        "findings": [
            Finding(
                task="状态管理",
                summary="状态在节点间传递。",
                key_points=[FindingPoint(text="状态可追踪", source_ids=["S1"])],
                source_ids=["S1"],
                source_urls=["https://docs.example.com/state"],
            ),
            Finding(
                task="条件路由",
                summary="路由由审核结果决定。",
                key_points=[FindingPoint(text="支持条件边", source_ids=["S2"])],
                source_ids=["S2"],
                source_urls=["https://docs.example.com/routing"],
            ),
        ],
        "sources": [
            Source(
                id="S1",
                title="状态文档",
                url="https://docs.example.com/state",
                relevance_score=0.9,
            ),
            Source(
                id="S2",
                title="路由文档",
                url="https://docs.example.com/routing",
                relevance_score=0.8,
            ),
        ],
        "review_result": None,
        "stage": "completed",
        "errors": [],
        "research_count": 2,
        "max_research_loops": 8,
        "retry_count": 0,
        "max_retries": 3,
        "content_filter_count": 0,
        "content_filter_recovered_count": 0,
        "defensive_retry_count": 0,
        "suspicious_sources_excluded": 0,
        "token_usage": 1234,
        "llm_calls": 5,
        "final_report": (
            "# 报告\n\n## 执行摘要\n状态可追踪。[S1]\n\n"
            "## 主要发现\n支持条件边。[S2]\n\n## 局限性\n样本有限。\n\n"
            "## 结论\n流程有效。[S1][S2]\n\n## 参考来源\n- [S1]\n- [S2]\n"
        ),
    }


def test_evaluation_metrics_pass_for_grounded_report() -> None:
    result = evaluate_research_state(make_evaluation_state(), duration_seconds=1.25)

    assert result.passed is True
    assert result.plan_coverage == 1
    assert result.citation_validity == 1
    assert result.evidence_citation_coverage == 1
    assert result.source_count == 2
    assert result.high_relevance_source_ratio == 1
    assert result.average_source_relevance == 0.85


def test_evaluation_metrics_detect_invalid_citation_and_missing_plan() -> None:
    state = make_evaluation_state()
    state["findings"] = state["findings"][:1]
    state["final_report"] += "\n无法验证的结论。[S99]"

    result = evaluate_research_state(state)

    assert result.passed is False
    assert result.plan_coverage == 0.5
    assert result.citation_validity < 1


def test_evaluation_summary_aggregates_results() -> None:
    result = evaluate_research_state(make_evaluation_state())

    summary = summarize_evaluations([result, result])

    assert summary.case_count == 2
    assert summary.pass_rate == 1
