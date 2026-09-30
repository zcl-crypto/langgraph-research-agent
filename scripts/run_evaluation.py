"""运行真实研究评测集，普通 pytest 不会执行本脚本。"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from time import perf_counter

from app.core.config import Settings
from app.evaluation.dataset import load_evaluation_dataset
from app.evaluation.metrics import (
    ResearchEvaluation,
    build_failure_result,
    evaluate_research_state,
    summarize_evaluations,
)
from app.services.research import build_research_service

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "evals" / "research_questions.json"


def write_results(path: Path, results: list[ResearchEvaluation]) -> None:
    """每完成一题就保存检查点，保留部分成功结果。"""

    summary = summarize_evaluations(results)
    payload = {
        "summary": summary.model_dump(mode="json"),
        "results": [result.model_dump(mode="json") for result in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def configure_console() -> None:
    """保证 Windows 控制台可以输出中文评测结果。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


async def run_evaluation(args: argparse.Namespace) -> int:
    """顺序运行评测问题，避免并发消耗不可控。"""

    cases = load_evaluation_dataset(args.dataset)
    if args.case_id:
        requested_ids = set(args.case_id)
        cases = [case for case in cases if case.id in requested_ids]
        missing_ids = requested_ids - {case.id for case in cases}
        if missing_ids:
            raise ValueError(f"评测数据集不存在 case id：{', '.join(sorted(missing_ids))}")
    elif args.max_cases is not None:
        cases = cases[: args.max_cases]
    print(f"评测数据集校验成功：{len(cases)} 条")
    if args.dry_run:
        for case in cases:
            print(f"- {case.id} [{case.category}] {case.query}")
        return 0

    service = build_research_service(Settings())
    results = []
    for index, case in enumerate(cases, start=1):
        print(f"\n[{index}/{len(cases)}] {case.id}: {case.query}")
        started_at = perf_counter()
        try:
            state = await service.run(case.query)
            result = evaluate_research_state(
                state,
                duration_seconds=perf_counter() - started_at,
                case_id=case.id,
                category=case.category,
            )
        except Exception as exc:
            result = build_failure_result(
                case_id=case.id,
                query=case.query,
                duration_seconds=perf_counter() - started_at,
                error=exc,
                category=case.category,
            )
            print(f"评测任务失败并已记录：{result.failure_reason}")
        results.append(result)
        print(result.model_dump_json(indent=2))
        if args.output:
            write_results(args.output, results)

    summary = summarize_evaluations(results)
    payload = {
        "summary": summary.model_dump(mode="json"),
        "results": [result.model_dump(mode="json") for result in results],
    }
    print("\n评测汇总：")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    if args.output:
        write_results(args.output, results)
        print(f"结果已写入：{args.output}")
    return 0 if summary.passed_count == summary.case_count else 1


def main() -> int:
    """解析命令行参数。"""

    configure_console()
    parser = argparse.ArgumentParser(description="运行 Research Agent 本地评测集")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run_evaluation(args))


if __name__ == "__main__":
    raise SystemExit(main())
