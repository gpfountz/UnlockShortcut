from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from unlockshortcut.daemon import SHORTCUTS_EXECUTABLE, Configuration, DailyRunner


def test_runs_shortcut_and_records_success(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def execute(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

    state_path: Path = tmp_path / "state.json"
    configuration: Configuration = Configuration("WANUsage", "unlockshortcut", "event")
    runner: DailyRunner = DailyRunner(configuration, state_path, execute)

    runner.handle_unlock()

    assert calls[0]["args"] == ([SHORTCUTS_EXECUTABLE, "run", "WANUsage"],)
    assert calls[0]["kwargs"]["input"] == "unlockshortcut\n"
    assert json.loads(state_path.read_text()) == {"completed_date": date.today().isoformat()}


def test_does_not_rerun_after_success_on_same_day(tmp_path: Path) -> None:
    state_path: Path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"completed_date": date.today().isoformat()}) + "\n")

    def execute(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("Shortcut should not run")

    configuration: Configuration = Configuration("WANUsage", "unlockshortcut", "event")
    DailyRunner(configuration, state_path, execute).handle_unlock()
