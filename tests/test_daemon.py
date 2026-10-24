# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.
from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from unlockshortcut.daemon import (
    SHORTCUTS_EXECUTABLE,
    Configuration,
    DailyRunner,
    load_configuration,
)


def test_runs_shortcuts_in_order_and_records_success(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def execute(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

    state_path: Path = tmp_path / "state.json"
    configuration: Configuration = Configuration(("WANUsage", "Archive Notes"), "event")
    runner: DailyRunner = DailyRunner(configuration, state_path, execute)

    runner.handle_unlock()

    assert calls[0]["args"] == ([SHORTCUTS_EXECUTABLE, "run", "WANUsage"],)
    assert calls[1]["args"] == ([SHORTCUTS_EXECUTABLE, "run", "Archive Notes"],)
    assert "input" not in calls[0]["kwargs"]
    assert json.loads(state_path.read_text()) == {
        "completed_date": date.today().isoformat(),
        "completed_shortcuts": ["WANUsage", "Archive Notes"],
        "run_date": date.today().isoformat(),
    }


def test_does_not_rerun_after_success_on_same_day(tmp_path: Path) -> None:
    state_path: Path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"completed_date": date.today().isoformat()}) + "\n")

    def execute(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("Shortcut should not run")

    configuration: Configuration = Configuration(("WANUsage",), "event")
    DailyRunner(configuration, state_path, execute).handle_unlock()


def test_resumes_after_failed_shortcut_without_repeating_success(tmp_path: Path) -> None:
    calls: list[str] = []

    def execute(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        shortcut_name: str = command[-1]
        calls.append(shortcut_name)
        return_code: int = 1 if shortcut_name == "Archive Notes" and len(calls) == 2 else 0
        return subprocess.CompletedProcess(command, return_code, stdout="", stderr="failed")

    state_path: Path = tmp_path / "state.json"
    configuration: Configuration = Configuration(("WANUsage", "Archive Notes"), "event")
    runner: DailyRunner = DailyRunner(configuration, state_path, execute)

    runner.handle_unlock()
    runner.handle_unlock()

    assert calls == ["WANUsage", "Archive Notes", "Archive Notes"]
    assert json.loads(state_path.read_text())["completed_date"] == date.today().isoformat()


def test_loads_shortcut_name_list(tmp_path: Path) -> None:
    config_path: Path = tmp_path / "config.toml"
    config_path.write_text('shortcut_names = ["WANUsage", "Archive Notes"]\n', encoding="utf-8")

    configuration: Configuration = load_configuration(config_path)

    assert configuration.shortcut_names == ("WANUsage", "Archive Notes")


def test_loads_legacy_shortcut_name(tmp_path: Path) -> None:
    config_path: Path = tmp_path / "config.toml"
    config_path.write_text('shortcut_name = "WANUsage"\n', encoding="utf-8")

    assert load_configuration(config_path).shortcut_names == ("WANUsage",)


@pytest.mark.parametrize(
    "configuration_text",
    ["shortcut_names = []\n", 'shortcut_names = ["WANUsage", "WANUsage"]\n'],
)
def test_rejects_invalid_shortcut_name_lists(tmp_path: Path, configuration_text: str) -> None:
    config_path: Path = tmp_path / "config.toml"
    config_path.write_text(configuration_text, encoding="utf-8")

    with pytest.raises(ValueError):
        load_configuration(config_path)
