"""
Agent CLI entry. 被 launchd wrapper 呼叫, 輸出完整 tick prompt 到 stdout,
由上游 pipe 給 `claude -p` 執行。

必須從 `backend/` 目錄執行 (pytest rootdir = backend/, 依賴 PYTHONPATH 為 backend/)。

Usage (從 backend/ 目錄):
    python -m scripts.agent_run --tick=evening
    python -m scripts.agent_run --tick=night
    python -m scripts.agent_run --tick=night --dry-run  # 不執行 site_restore, 只印 prompt 骨架
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_DIR = REPO_ROOT / "backend" / "app" / "agent" / "prompts"

VALID_TICKS = {"evening", "night"}


def _load_prompt(tick: str) -> str:
    fn = PROMPT_DIR / f"tick_{tick}.md"
    if not fn.exists():
        return f"# {tick.capitalize()} Tick prompt (placeholder, tick_{tick}.md not yet created)"
    return fn.read_text()


def _render_site_restore_section(dry_run: bool) -> str:
    if dry_run:
        return "## site_restore (dry-run, skipped)\n"
    from app.agent.site_restore import run_checklist
    report = run_checklist(repo_root=REPO_ROOT)
    lines = ["## site_restore 結果"]
    lines.append(f"- git_dirty: {report.git_dirty}")
    lines.append(f"- stale_lock: {report.stale_lock}")
    lines.append(f"- missing_end_marker: {report.missing_end_marker}")
    lines.append(f"- critical: {report.critical}")
    if report.findings:
        lines.append("### findings")
        for f in report.findings:
            lines.append(f"- {f}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tick", required=True, help="evening | night")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.tick not in VALID_TICKS:
        print(f"unknown tick '{args.tick}', expected {VALID_TICKS}", file=sys.stderr)
        return 2

    sections = [
        _load_prompt(args.tick),
        _render_site_restore_section(dry_run=args.dry_run),
    ]
    print("\n\n".join(sections))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
