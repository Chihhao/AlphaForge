from __future__ import annotations
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List
from app.agent.deploy_lock import load as load_lock, LockStatus

TAIPEI_TZ = timezone(timedelta(hours=8))
STALE_THRESHOLD_MIN = 30


@dataclass
class SiteReport:
    git_dirty: bool = False
    stale_lock: bool = False
    missing_end_marker: bool = False
    critical: bool = False
    findings: List[str] = field(default_factory=list)


def _git_status(repo_root: Path) -> str:
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def _now_minus_minutes(iso_timestamp: str) -> float:
    ts = datetime.fromisoformat(iso_timestamp)
    now = datetime.now(TAIPEI_TZ)
    return (now - ts).total_seconds() / 60


def run_checklist(repo_root: Path) -> SiteReport:
    report = SiteReport()

    # git status
    dirty = _git_status(repo_root)
    if dirty:
        report.git_dirty = True
        report.critical = True
        report.findings.append(f"git status unclean:\n{dirty}")

    # deploy-lock 過時 in_progress
    lock_file = repo_root / "docs" / "state" / "deploy-lock.json"
    lock = load_lock(lock_file)
    if lock is not None and lock.status == LockStatus.IN_PROGRESS:
        age_min = _now_minus_minutes(lock.timestamp)
        if age_min > STALE_THRESHOLD_MIN:
            report.stale_lock = True
            report.critical = True
            report.findings.append(
                f"deploy-lock in_progress {age_min:.1f} min, possibly stale"
            )

    # 最近 report 是否有 END 標記
    reports_dir = repo_root / "docs" / "reports"
    if reports_dir.exists():
        md_files = sorted(reports_dir.glob("*.md"), reverse=True)
        if md_files:
            latest = md_files[0].read_text()
            if "END:" not in latest:
                report.missing_end_marker = True
                report.critical = True
                report.findings.append(f"{md_files[0].name} 缺 END 標記, 前次 tick 可能被砍")

    return report
