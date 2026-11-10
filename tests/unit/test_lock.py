from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ufabc_science.pipeline.lock import ConcurrentRunError, PipelineLock


def test_lock_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lock"
    first = PipelineLock(path, run_id="a", stale_after=timedelta(hours=1))
    second = PipelineLock(path, run_id="b", stale_after=timedelta(hours=1))
    with first:
        assert path.exists()
        with pytest.raises(ConcurrentRunError, match="run_id=a"):
            second.acquire()
    assert not path.exists()
    with second:
        assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == "b"


def test_stale_lock_is_recovered(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lock"
    old = datetime.now(timezone.utc) - timedelta(hours=10)
    path.write_text(
        json.dumps({"run_id": "velho", "started_at": old.isoformat()}), encoding="utf-8"
    )
    with PipelineLock(path, run_id="novo", stale_after=timedelta(hours=6)):
        assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == "novo"


def test_release_does_not_remove_lock_of_another_run(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lock"
    lock = PipelineLock(path, run_id="a", stale_after=timedelta(hours=1))
    lock.acquire()
    path.write_text(json.dumps({"run_id": "outro"}), encoding="utf-8")
    lock.release()
    assert path.exists()
