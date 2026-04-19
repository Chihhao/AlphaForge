from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

TAIPEI_TZ = timezone(timedelta(hours=8))


class LockStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    RELEASED = "released"


@dataclass
class DeployLock:
    timestamp: str
    tick: str
    previous_commit_sha: str
    previous_backend_image: str
    new_commit_sha: str
    status: LockStatus

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DeployLock":
        return cls(
            timestamp=d["timestamp"],
            tick=d["tick"],
            previous_commit_sha=d["previous_commit_sha"],
            previous_backend_image=d["previous_backend_image"],
            new_commit_sha=d["new_commit_sha"],
            status=LockStatus(d["status"]),
        )


def absent(lock_file: Path) -> bool:
    return not lock_file.exists()


def load(lock_file: Path) -> Optional[DeployLock]:
    if absent(lock_file):
        return None
    with lock_file.open("r") as f:
        return DeployLock.from_dict(json.load(f))


def _write(lock_file: Path, lock: DeployLock) -> None:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("w") as f:
        json.dump(lock.to_dict(), f, indent=2)


def begin(lock_file: Path, *, tick: str, previous_commit_sha: str,
          previous_backend_image: str, new_commit_sha: str) -> DeployLock:
    lock = DeployLock(
        timestamp=datetime.now(TAIPEI_TZ).isoformat(),
        tick=tick,
        previous_commit_sha=previous_commit_sha,
        previous_backend_image=previous_backend_image,
        new_commit_sha=new_commit_sha,
        status=LockStatus.IN_PROGRESS,
    )
    _write(lock_file, lock)
    return lock


_VALID_TRANSITIONS = {
    LockStatus.IN_PROGRESS: {LockStatus.SUCCESS},
    LockStatus.SUCCESS: {LockStatus.RELEASED},
}


def advance(lock_file: Path, to: LockStatus) -> DeployLock:
    lock = load(lock_file)
    if lock is None:
        raise ValueError("no lock file to advance")
    if to not in _VALID_TRANSITIONS.get(lock.status, set()):
        raise ValueError(f"invalid transition {lock.status.value} -> {to.value}")
    lock.status = to
    lock.timestamp = datetime.now(TAIPEI_TZ).isoformat()
    _write(lock_file, lock)
    return lock


def release(lock_file: Path) -> DeployLock:
    return advance(lock_file, LockStatus.RELEASED)
