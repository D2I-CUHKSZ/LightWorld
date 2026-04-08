# -*- coding: utf-8 -*-
from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from app.utils.report_agent import ReportAgent, ReportOutline, ReportSection


def test_normalize_outline_adds_history_and_forecast_sections():
    outline = ReportOutline(
        title="武汉大学舆情分析",
        summary="测试摘要",
        sections=[
            ReportSection(title="事件引爆与跨平台分化传播"),
            ReportSection(title="主体行动图谱：从沉默到协同施压"),
            ReportSection(title="影响力非对称性揭示结构性风险"),
        ],
    )

    normalized = ReportAgent._normalize_outline(outline)

    assert len(normalized.sections) >= 3
    assert "历史" in normalized.sections[0].title
    assert any("演化" in section.title or "模拟" in section.title for section in normalized.sections)
    assert any("预测" in section.title or "未来" in section.title for section in normalized.sections)
    assert "预测" in normalized.sections[-1].title or "未来" in normalized.sections[-1].title


def test_normalize_outline_moves_existing_forecast_to_last_section():
    outline = ReportOutline(
        title="校园事件报告",
        summary="测试摘要",
        sections=[
            ReportSection(title="未来走势判断", description="已有预测章节"),
            ReportSection(title="历史事件回顾"),
            ReportSection(title="平台扩散与群体互动"),
        ],
    )

    normalized = ReportAgent._normalize_outline(outline)

    assert normalized.sections[-1].title == "未来走势判断"
    assert normalized.sections[-1].description == "已有预测章节"
    assert "历史" in normalized.sections[0].title
