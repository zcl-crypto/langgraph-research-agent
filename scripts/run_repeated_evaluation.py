"""重复运行核心与内容安全评测，并持续保存可恢复的结果。"""

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from app.core.config import Settings
from app.evaluation.dataset import EvaluationCase, load_evaluation_dataset
from app.evaluation.metrics import (
    ResearchEvaluation,
    build_failure_result,
    evaluate_research_state,
    summarize_evaluations,
)
from app.services.research import build_research_service

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORE_DATASET = PROJECT_ROOT / "evals" / "research_questions.json"
DEFAULT_SAFETY_DATASET = PROJECT_ROOT / "evals" / "content_filter_questions.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evals" / "repeated" / "latest"


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_results(path: Path) -> list[ResearchEvaluation]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [ResearchEvaluation.model_validate(item) for item in payload["results"]]


def _is_provider_limit(result: ResearchEvaluation) -> bool:
    reason = (result.failure_reason or "").lower()
    signals = ("429", "quota", "rate limit", "余额", "额度", "1305")
    return any(signal in reason for signal in signals)


def build_repeated_summary(
    results: list[ResearchEvaluation],
    *,
    cases: list[EvaluationCase],
    rounds: int,
) -> dict[str, Any]:
    base = summarize_evaluations(results).model_dump(mode="json")
    grouped: dict[str, list[ResearchEvaluation]] = defaultdict(list)
    for result in results:
        grouped[result.case_id].append(result)
    stable_case_count = sum(
        len(grouped[case.id]) == rounds and all(item.passed for item in grouped[case.id])
        for case in cases
    )
    safety_results = [result for result in results if result.category == "内容安全"]
    core_results = [result for result in results if result.category != "内容安全"]
    expected_run_count = len(cases) * rounds
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "expected_run_count": expected_run_count,
        "recorded_run_count": len(results),
        "rounds": rounds,
        "unique_case_count": len(cases),
        "stable_case_count": stable_case_count,
        "stable_pass_rate": round(stable_case_count / len(cases), 4) if cases else 0,
        "core_run_count": len(core_results),
        "core_pass_rate": (
            round(sum(item.passed for item in core_results) / len(core_results), 4)
            if core_results
            else 0
        ),
        "safety_run_count": len(safety_results),
        "safety_pass_rate": (
            round(sum(item.passed for item in safety_results) / len(safety_results), 4)
            if safety_results
            else 0
        ),
        "batch_abort_count": 0,
        **base,
    }


def _render_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# 多轮真实评测汇总",
            "",
            f"- 生成时间：{summary['generated_at']}",
            f"- 计划运行：{summary['expected_run_count']}",
            f"- 已记录：{summary['recorded_run_count']}",
            f"- 任务完成率：{float(summary['completion_rate']):.2%}",
            f"- 综合通过率：{float(summary['pass_rate']):.2%}",
            f"- 核心任务通过率：{float(summary['core_pass_rate']):.2%}",
            f"- 内容安全任务通过率：{float(summary['safety_pass_rate']):.2%}",
            f"- 稳定通过率：{float(summary['stable_pass_rate']):.2%}",
            f"- 内容安全触发任务：{summary['content_filter_case_count']}",
            f"- 内容安全事件：{summary['content_filter_event_count']}",
            f"- 内容安全恢复事件：{summary['content_filter_recovered_count']}",
            f"- 内容安全恢复率：{float(summary['content_filter_recovery_rate']):.2%}",
            f"- 防御性重试：{summary['defensive_retry_count']}",
            f"- 排除可疑来源：{summary['suspicious_sources_excluded']}",
            f"- 批次中断：{summary['batch_abort_count']}",
            f"- 平均研究轮数：{float(summary['average_research_loops']):.2f}",
            f"- 平均 LLM 调用：{float(summary['average_llm_calls']):.2f}",
            f"- 平均 Token：{float(summary['average_token_usage']):.0f}",
            (
                f"- 耗时 P50 / P95：{float(summary['duration_p50_seconds']):.2f} / "
                f"{float(summary['duration_p95_seconds']):.2f} 秒"
            ),
            "",
            "自动指标不等同于人工答案正确率或引用语义支持率。",
        ]
    )


def _write_combined_outputs(
    output_dir: Path,
    results: list[ResearchEvaluation],
    *,
    cases: list[EvaluationCase],
    rounds: int,
) -> None:
    summary = build_repeated_summary(results, cases=cases, rounds=rounds)
    _write_json(output_dir / "summary.json", summary)
    (output_dir / "summary.md").write_text(
        _render_markdown(summary),
        encoding="utf-8",
    )
    jsonl = "\n".join(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        for result in results
    )
    (output_dir / "results.jsonl").write_text(
        f"{jsonl}\n" if jsonl else "",
        encoding="utf-8",
    )


async def run_repeated_evaluation(args: argparse.Namespace) -> int:
    core_cases = load_evaluation_dataset(args.core_dataset)[: args.core_count]
    safety_cases = load_evaluation_dataset(args.safety_dataset)
    cases = [*core_cases, *safety_cases]
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("核心与内容安全数据集的 case id 不能重复")

    print(
        f"多轮评测：{len(core_cases)} 条核心 + {len(safety_cases)} 条安全，"
        f"共 {args.rounds} 轮 / {len(cases) * args.rounds} 次"
    )
    if args.dry_run:
        for round_number in range(1, args.rounds + 1):
            for case in cases:
                print(f"- round={round_number} {case.id} [{case.category}]")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    service = build_research_service(Settings())
    all_results: list[ResearchEvaluation] = []
    for round_number in range(1, args.rounds + 1):
        round_path = args.output_dir / f"run-{round_number:02d}.json"
        round_results = _load_results(round_path)
        completed_ids = {result.case_id for result in round_results}
        all_results.extend(round_results)
        for index, case in enumerate(cases, start=1):
            if case.id in completed_ids:
                print(f"[round {round_number} {index}/{len(cases)}] 跳过已记录：{case.id}")
                continue
            print(f"[round {round_number} {index}/{len(cases)}] {case.id}: {case.query}")
            started_at = perf_counter()
            try:
                state = await service.run(case.query)
                result = evaluate_research_state(
                    state,
                    duration_seconds=perf_counter() - started_at,
                    case_id=case.id,
                    category=case.category,
                    round_number=round_number,
                )
            except Exception as exc:
                result = build_failure_result(
                    case_id=case.id,
                    query=case.query,
                    duration_seconds=perf_counter() - started_at,
                    error=exc,
                    category=case.category,
                    round_number=round_number,
                )
            round_results.append(result)
            all_results.append(result)
            round_payload = {
                "round": round_number,
                "summary": summarize_evaluations(round_results).model_dump(mode="json"),
                "results": [item.model_dump(mode="json") for item in round_results],
            }
            _write_json(round_path, round_payload)
            _write_combined_outputs(
                args.output_dir,
                all_results,
                cases=cases,
                rounds=args.rounds,
            )
            print(result.model_dump_json(indent=2))
            if args.stop_on_provider_limit and _is_provider_limit(result):
                print("检测到供应商限流或额度错误，已保存检查点并停止后续调用。")
                return 2

    summary = build_repeated_summary(all_results, cases=cases, rounds=args.rounds)
    _write_combined_outputs(
        args.output_dir,
        all_results,
        cases=cases,
        rounds=args.rounds,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(summary["passed_count"] != summary["expected_run_count"])


def main() -> int:
    configure_console()
    parser = argparse.ArgumentParser(description="重复运行 Research Agent 真实评测")
    parser.add_argument("--core-dataset", type=Path, default=DEFAULT_CORE_DATASET)
    parser.add_argument("--safety-dataset", type=Path, default=DEFAULT_SAFETY_DATASET)
    parser.add_argument("--core-count", type=int, default=6)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--stop-on-provider-limit",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run_repeated_evaluation(args))


if __name__ == "__main__":
    raise SystemExit(main())
