from __future__ import annotations
from datetime import date
from app.agent.report_builder import build_evening_skeleton, build_night_skeleton


def test_evening_skeleton_has_mandatory_sections():
    md = build_evening_skeleton(report_date=date(2026, 4, 20))
    assert "# 2026-04-20 Evening Tick (18:30)" in md
    assert "## 產線體檢" in md
    assert "## Alpha ledger" in md
    assert "## 可逆清單" in md
    assert "END:" in md  # 尾端 END 標記


def test_night_skeleton_has_mandatory_sections():
    md = build_night_skeleton(report_date=date(2026, 4, 20))
    assert "# 2026-04-20 Night Tick (03:00)" in md
    assert "## 候選題 + Gate 2 checklist" in md
    assert "## 執行摘要" in md
    assert "## Alpha ledger" in md
    assert "## 可逆清單" in md
    assert "END:" in md
