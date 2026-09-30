import math
import re

from pydantic import BaseModel, Field

from app.core.exceptions import LLMContentFilterError
from app.graph.state import ResearchState

_CITATION_PATTERN = re.compile(r"\[(S\d+)\]")
_REQUIRED_REPORT_SECTIONS = ("## 执行摘要", "## 局限性", "## 结论", "## 参考来源")


class EvaluationThresholds(BaseModel):
    """本地回归评测的最低通过标准。"""

    plan_coverage: float = Field(default=1.0, ge=0, le=1)
    citation_validity: float = Field(default=1.0, ge=0, le=1)
    evidence_citation_coverage: float = Field(default=0.8, ge=0, le=1)
    minimum_sources: int = Field(default=1, ge=0)


class ResearchEvaluation(BaseModel):
    """单次研究的可解释质量指标。"""

    task_id: str
    case_id: str = ""
    category: str = ""
    round_number: int = 1
    query: str
    completed: bool
    plan_coverage: float
    citation_validity: float
    evidence_citation_coverage: float
    full_text_source_ratio: float
    high_relevance_source_ratio: float
    average_source_relevance: float
    source_count: int
    suspicious_source_count: int
    report_has_required_sections: bool
    error_count: int
    research_loops: int
    retry_count: int
    content_filter_count: int
    content_filter_recovered_count: int
    defensive_retry_count: int
    suspicious_sources_excluded: int
    token_usage: int
    llm_calls: int
    duration_seconds: float = 0
    passed: bool
    failure_reason: str | None = None


class EvaluationSummary(BaseModel):
    """一批研究评测的汇总结果。"""

    case_count: int
    completed_count: int
    completion_rate: float
    passed_count: int
    pass_rate: float
    average_plan_coverage: float
    average_citation_validity: float
    average_evidence_citation_coverage: float
    average_source_relevance: float
    average_duration_seconds: float
    duration_p50_seconds: float
    duration_p95_seconds: float
    average_research_loops: float
    average_llm_calls: float
    average_token_usage: float
    content_filter_case_count: int
    content_filter_event_count: int
    content_filter_recovered_case_count: int
    content_filter_recovered_count: int
    content_filter_recovery_rate: float
    defensive_retry_count: int
    suspicious_source_count: int
    suspicious_sources_excluded: int
    batch_failure_count: int


def build_failure_result(
    *,
    case_id: str,
    query: str,
    duration_seconds: float,
    error: Exception,
    category: str = "",
    round_number: int = 1,
) -> ResearchEvaluation:
    """把单题异常记录为失败结果，避免整批评测丢失。"""

    content_filter_count = int(isinstance(error, LLMContentFilterError))
    return ResearchEvaluation(
        task_id=f"evaluation-failed:{case_id}",
        case_id=case_id,
        category=category,
        round_number=round_number,
        query=query,
        completed=False,
        plan_coverage=0,
        citation_validity=0,
        evidence_citation_coverage=0,
        full_text_source_ratio=0,
        high_relevance_source_ratio=0,
        average_source_relevance=0,
        source_count=0,
        suspicious_source_count=0,
        report_has_required_sections=False,
        error_count=1,
        research_loops=0,
        retry_count=0,
        content_filter_count=content_filter_count,
        content_filter_recovered_count=0,
        defensive_retry_count=0,
        suspicious_sources_excluded=0,
        token_usage=0,
        llm_calls=0,
        duration_seconds=round(duration_seconds, 3),
        passed=False,
        failure_reason=f"{type(error).__name__}: {error}",
    )


def _ratio(numerator: int, denominator: int, *, empty_value: float = 0.0) -> float:
    if denominator == 0:
        return empty_value
    return round(numerator / denominator, 4)


def evaluate_research_state(
    state: ResearchState,
    *,
    duration_seconds: float = 0,
    thresholds: EvaluationThresholds | None = None,
    case_id: str = "",
    category: str = "",
    round_number: int = 1,
) -> ResearchEvaluation:
    """根据 State 和最终报告计算计划覆盖、引用与来源指标。"""

    active_thresholds = thresholds or EvaluationThresholds()
    completed_tasks = {
        finding.task for finding in state["findings"] if finding.source_ids
    }
    completed_plan_tasks = sum(task in completed_tasks for task in state["plan"])
    plan_coverage = _ratio(
        completed_plan_tasks,
        len(state["plan"]),
        empty_value=1.0,
    )

    sources = [source for source in state["sources"] if source.acquisition != "read_failed"]
    valid_source_ids = {source.id for source in sources}
    cited_ids = _CITATION_PATTERN.findall(state["final_report"])
    valid_citation_count = sum(source_id in valid_source_ids for source_id in cited_ids)
    citation_validity = _ratio(
        valid_citation_count,
        len(cited_ids),
        empty_value=0.0,
    )
    evidence_source_ids = {
        source_id
        for finding in state["findings"]
        for source_id in finding.source_ids
    }
    cited_source_ids = set(cited_ids)
    evidence_citation_coverage = _ratio(
        len(evidence_source_ids & cited_source_ids),
        len(evidence_source_ids),
        empty_value=1.0,
    )
    full_text_source_ratio = _ratio(
        sum(source.acquisition == "webpage" for source in sources),
        len(sources),
        empty_value=0.0,
    )
    scored_sources = [
        source.relevance_score
        for source in sources
        if source.relevance_score is not None
    ]
    high_relevance_source_ratio = _ratio(
        sum(score >= 0.7 for score in scored_sources),
        len(scored_sources),
        empty_value=0.0,
    )
    average_source_relevance = (
        round(sum(scored_sources) / len(scored_sources), 4) if scored_sources else 0.0
    )
    report_has_required_sections = all(
        heading in state["final_report"] for heading in _REQUIRED_REPORT_SECTIONS
    )
    passed = (
        state["stage"] == "completed"
        and plan_coverage >= active_thresholds.plan_coverage
        and citation_validity >= active_thresholds.citation_validity
        and evidence_citation_coverage
        >= active_thresholds.evidence_citation_coverage
        and len(sources) >= active_thresholds.minimum_sources
        and report_has_required_sections
    )
    return ResearchEvaluation(
        task_id=state["task_id"],
        case_id=case_id,
        category=category,
        round_number=round_number,
        query=state["query"],
        completed=state["stage"] == "completed",
        plan_coverage=plan_coverage,
        citation_validity=citation_validity,
        evidence_citation_coverage=evidence_citation_coverage,
        full_text_source_ratio=full_text_source_ratio,
        high_relevance_source_ratio=high_relevance_source_ratio,
        average_source_relevance=average_source_relevance,
        source_count=len(sources),
        suspicious_source_count=sum(source.suspicious_content for source in sources),
        report_has_required_sections=report_has_required_sections,
        error_count=len(state["errors"]),
        research_loops=state["research_count"],
        retry_count=state["retry_count"],
        content_filter_count=state["content_filter_count"],
        content_filter_recovered_count=state["content_filter_recovered_count"],
        defensive_retry_count=state["defensive_retry_count"],
        suspicious_sources_excluded=state["suspicious_sources_excluded"],
        token_usage=state["token_usage"],
        llm_calls=state["llm_calls"],
        duration_seconds=round(duration_seconds, 3),
        passed=passed,
    )


def summarize_evaluations(results: list[ResearchEvaluation]) -> EvaluationSummary:
    """汇总一批评测结果，便于版本间回归对比。"""

    count = len(results)
    if count == 0:
        return EvaluationSummary(
            case_count=0,
            completed_count=0,
            completion_rate=0,
            passed_count=0,
            pass_rate=0,
            average_plan_coverage=0,
            average_citation_validity=0,
            average_evidence_citation_coverage=0,
            average_source_relevance=0,
            average_duration_seconds=0,
            duration_p50_seconds=0,
            duration_p95_seconds=0,
            average_research_loops=0,
            average_llm_calls=0,
            average_token_usage=0,
            content_filter_case_count=0,
            content_filter_event_count=0,
            content_filter_recovered_case_count=0,
            content_filter_recovered_count=0,
            content_filter_recovery_rate=0,
            defensive_retry_count=0,
            suspicious_source_count=0,
            suspicious_sources_excluded=0,
            batch_failure_count=0,
        )

    def average(values: list[float]) -> float:
        return round(sum(values) / count, 4)

    def percentile(values: list[float], quantile: float) -> float:
        ordered = sorted(values)
        position = (len(ordered) - 1) * quantile
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return round(ordered[lower], 4)
        weight = position - lower
        return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 4)

    completed_count = sum(result.completed for result in results)
    passed_count = sum(result.passed for result in results)
    filtered_cases = sum(result.content_filter_count > 0 for result in results)
    recovered_cases = sum(
        result.content_filter_recovered_count > 0 for result in results
    )
    content_filter_events = sum(result.content_filter_count for result in results)
    recovered_events = sum(
        result.content_filter_recovered_count for result in results
    )
    durations = [result.duration_seconds for result in results]
    return EvaluationSummary(
        case_count=count,
        completed_count=completed_count,
        completion_rate=_ratio(completed_count, count),
        passed_count=passed_count,
        pass_rate=_ratio(passed_count, count),
        average_plan_coverage=average([result.plan_coverage for result in results]),
        average_citation_validity=average([result.citation_validity for result in results]),
        average_evidence_citation_coverage=average(
            [result.evidence_citation_coverage for result in results]
        ),
        average_source_relevance=average(
            [result.average_source_relevance for result in results]
        ),
        average_duration_seconds=average([result.duration_seconds for result in results]),
        duration_p50_seconds=percentile(durations, 0.5),
        duration_p95_seconds=percentile(durations, 0.95),
        average_research_loops=average(
            [float(result.research_loops) for result in results]
        ),
        average_llm_calls=average([float(result.llm_calls) for result in results]),
        average_token_usage=average([float(result.token_usage) for result in results]),
        content_filter_case_count=filtered_cases,
        content_filter_event_count=content_filter_events,
        content_filter_recovered_case_count=recovered_cases,
        content_filter_recovered_count=recovered_events,
        content_filter_recovery_rate=_ratio(recovered_events, content_filter_events),
        defensive_retry_count=sum(result.defensive_retry_count for result in results),
        suspicious_source_count=sum(
            result.suspicious_source_count for result in results
        ),
        suspicious_sources_excluded=sum(
            result.suspicious_sources_excluded for result in results
        ),
        batch_failure_count=count - completed_count,
    )
