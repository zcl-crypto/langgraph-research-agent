from app.graph.nodes.writer import _render_report
from app.models.llm_outputs import ReportOutput
from app.models.research import Source


def test_render_report_cleans_wrappers_and_builds_one_reference_section() -> None:
    output = ReportOutput(
        title="```markdown\n# 测试报告\n```",
        executive_summary="执行摘要 [S99]",
        main_findings=["核心事实"],
        analysis=["综合分析"],
        limitations="样本有限",
        conclusion="结论成立",
        citations={
            "executive_summary": ["S1"],
            "main_findings_1": ["S1"],
            "analysis_1": ["S1"],
            "conclusion": ["S1"],
        },
    )
    sources = [
        Source(
            id="S1",
            title="官方文档",
            url="https://example.com/docs",
            relevance_score=0.9,
        )
    ]

    report = _render_report(output, sources)

    assert "```" not in report
    assert "[S99]" not in report
    assert report.count("## 参考来源") == 1
    assert "核心事实 [S1]" in report
    assert "相关性 0.90" in report
