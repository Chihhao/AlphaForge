from __future__ import annotations
import subprocess
from pathlib import Path
from unittest.mock import patch
from app.agent.site_restore import run_checklist, SiteReport


def _git_init(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "x.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)


def test_clean_repo_no_lock_no_report(tmp_path: Path):
    _git_init(tmp_path)
    report = run_checklist(repo_root=tmp_path)
    assert isinstance(report, SiteReport)
    assert report.git_dirty is False
    assert report.stale_lock is False
    assert report.critical is False


def test_dirty_repo_flags_critical(tmp_path: Path):
    _git_init(tmp_path)
    (tmp_path / "dirty.txt").write_text("uncommitted")
    report = run_checklist(repo_root=tmp_path)
    assert report.git_dirty is True
    assert report.critical is True


def test_stale_in_progress_lock_flags_critical(tmp_path: Path):
    _git_init(tmp_path)
    from app.agent.deploy_lock import begin
    lock_file = tmp_path / "docs/state/deploy-lock.json"
    begin(lock_file, tick="0300", previous_commit_sha="a",
          previous_backend_image="img", new_commit_sha="b")
    # 假裝 30 分鐘前開始
    with patch("app.agent.site_restore._now_minus_minutes", return_value=31):
        report = run_checklist(repo_root=tmp_path)
    assert report.stale_lock is True
    assert report.critical is True
