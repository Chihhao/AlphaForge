import json
from pathlib import Path
import pytest
from app.agent.deploy_lock import (
    DeployLock, LockStatus, load, begin, advance, release, absent,
)


def test_absent_when_file_missing(tmp_path: Path):
    lock_file = tmp_path / "deploy-lock.json"
    assert absent(lock_file) is True
    assert load(lock_file) is None


def test_begin_writes_in_progress(tmp_path: Path):
    lock_file = tmp_path / "deploy-lock.json"
    lock = begin(
        lock_file,
        tick="0300",
        previous_commit_sha="abc",
        previous_backend_image="alphaforge-backend:20260419",
        new_commit_sha="def",
    )
    assert lock.status == LockStatus.IN_PROGRESS
    loaded = load(lock_file)
    assert loaded.status == LockStatus.IN_PROGRESS
    assert loaded.new_commit_sha == "def"


def test_advance_in_progress_to_success(tmp_path: Path):
    lock_file = tmp_path / "deploy-lock.json"
    begin(lock_file, tick="0300", previous_commit_sha="a",
          previous_backend_image="img", new_commit_sha="b")
    advanced = advance(lock_file, LockStatus.SUCCESS)
    assert advanced.status == LockStatus.SUCCESS


def test_release_after_success(tmp_path: Path):
    lock_file = tmp_path / "deploy-lock.json"
    begin(lock_file, tick="0300", previous_commit_sha="a",
          previous_backend_image="img", new_commit_sha="b")
    advance(lock_file, LockStatus.SUCCESS)
    released = release(lock_file)
    assert released.status == LockStatus.RELEASED


def test_advance_rejects_invalid_transition(tmp_path: Path):
    lock_file = tmp_path / "deploy-lock.json"
    begin(lock_file, tick="0300", previous_commit_sha="a",
          previous_backend_image="img", new_commit_sha="b")
    with pytest.raises(ValueError, match="invalid transition"):
        advance(lock_file, LockStatus.RELEASED)  # must go through SUCCESS
