"""A launchd-friendly daemon that invokes Shortcuts on the first unlock each day."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import objc
from Foundation import (
    NSDistributedNotificationCenter,
    NSNotificationSuspensionBehaviorDeliverImmediately,
    NSObject,
)
from PyObjCTools import AppHelper

CONFIG_DIRECTORY: Final[Path] = Path.home() / ".config" / "UnlockShortcut"
CONFIG_PATH: Final[Path] = CONFIG_DIRECTORY / "config.toml"
STATE_PATH: Final[Path] = CONFIG_DIRECTORY / "state.json"
LOG_PATH: Final[Path] = CONFIG_DIRECTORY / "unlockshortcut.log"
SHORTCUTS_EXECUTABLE: Final[str] = "/usr/bin/shortcuts"
DEFAULT_UNLOCK_NOTIFICATION: Final[str] = "com.apple.screenIsUnlocked"


@dataclass(frozen=True)
class Configuration:
    """Configuration read from config.toml."""

    shortcut_names: tuple[str, ...]
    unlock_notification: str


def _required_text(values: dict[str, object], key: str) -> str:
    value: object | None = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_text(values: dict[str, object], key: str, default: str) -> str:
    value: object = values.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _shortcut_names(values: dict[str, object]) -> tuple[str, ...]:
    """Return the configured Shortcut names, accepting the legacy singular key."""
    names_value: object | None = values.get("shortcut_names")
    if names_value is None:
        return (_required_text(values, "shortcut_name"),)
    if not isinstance(names_value, list) or not names_value:
        raise ValueError("shortcut_names must be a non-empty list of strings")
    if not all(isinstance(name, str) and name.strip() for name in names_value):
        raise ValueError("shortcut_names must contain only non-empty strings")
    names: tuple[str, ...] = tuple(name for name in names_value if isinstance(name, str))
    if len(set(names)) != len(names):
        raise ValueError("shortcut_names must not contain duplicates")
    return names


def load_configuration(path: Path = CONFIG_PATH) -> Configuration:
    """Load and validate the daemon configuration."""
    with path.open("rb") as config_file:
        values: dict[str, object] = tomllib.load(config_file)
    return Configuration(
        shortcut_names=_shortcut_names(values),
        unlock_notification=_optional_text(
            values, "unlock_notification", DEFAULT_UNLOCK_NOTIFICATION
        ),
    )


class DailyRunner:
    """Runs configured Shortcuts in order after the first unlock each day."""

    def __init__(
        self,
        configuration: Configuration,
        state_path: Path = STATE_PATH,
        execute: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._configuration: Configuration = configuration
        self._state_path: Path = state_path
        self._execute: Callable[..., subprocess.CompletedProcess[str]] = execute

    def _read_state(self) -> dict[str, object]:
        """Read saved progress, returning an empty state when recovery is needed."""
        try:
            state_value: object = json.loads(self._state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            logging.exception("Unable to read state file; retrying the Shortcuts")
            return {}
        if not isinstance(state_value, dict):
            logging.error("State file is not an object; retrying the Shortcuts")
            return {}
        return {key: value for key, value in state_value.items() if isinstance(key, str)}

    def _completed_names(self, today: str) -> list[str]:
        """Return Shortcut names already completed today."""
        state: dict[str, object] = self._read_state()
        if state.get("completed_date") == today:
            return list(self._configuration.shortcut_names)
        if state.get("run_date") != today:
            return []
        completed_value: object | None = state.get("completed_shortcuts")
        if not isinstance(completed_value, list):
            return []
        return [name for name in completed_value if isinstance(name, str)]

    def _record_progress(self, today: str, completed_names: list[str]) -> None:
        """Atomically save the successful Shortcut names for today."""
        self._state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary_path: Path = self._state_path.with_suffix(".tmp")
        state: dict[str, object] = {
            "run_date": today,
            "completed_shortcuts": completed_names,
        }
        if len(completed_names) == len(self._configuration.shortcut_names):
            state["completed_date"] = today
        temporary_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
        temporary_path.replace(self._state_path)

    def _run_shortcut(self, shortcut_name: str) -> bool:
        """Run one Shortcut and report whether it completed successfully."""
        logging.info("Running Shortcut %r", shortcut_name)
        result: subprocess.CompletedProcess[str] = self._execute(
            [SHORTCUTS_EXECUTABLE, "run", shortcut_name],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode == 0:
            logging.info("Shortcut %r completed successfully", shortcut_name)
            return True
        logging.error(
            "Shortcut %r failed (exit %s): %s",
            shortcut_name,
            result.returncode,
            result.stderr.strip(),
        )
        return False

    def handle_unlock(self) -> None:
        """Run each pending Shortcut and preserve progress if one fails."""
        today: str = date.today().isoformat()
        completed_names: list[str] = self._completed_names(today)
        if len(completed_names) == len(self._configuration.shortcut_names):
            logging.info("Screen unlocked; all Shortcuts already completed today")
            return

        logging.info("Screen unlocked; running pending Shortcuts")
        completed_set: set[str] = set(completed_names)
        for shortcut_name in self._configuration.shortcut_names:
            if shortcut_name in completed_set:
                continue
            if not self._run_shortcut(shortcut_name):
                return
            completed_names.append(shortcut_name)
            completed_set.add(shortcut_name)
            self._record_progress(today, completed_names)
        logging.info("All Shortcuts completed successfully")


def configure_logging() -> None:
    """Log to the user-owned configuration directory and standard error."""
    CONFIG_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
    )


class UnlockObserver(NSObject):  # type: ignore[misc]
    """Bridge macOS notifications to the typed application runner."""

    def initWithRunner_(self, event_runner: DailyRunner) -> UnlockObserver:
        objc.super(UnlockObserver, self).init()
        self._event_runner: DailyRunner = event_runner
        return self

    def screenUnlocked_(self, _notification: object) -> None:
        self._event_runner.handle_unlock()


def run_event_loop(runner: DailyRunner, notification_name: str) -> None:
    """Subscribe to the macOS distributed unlock notification indefinitely."""
    center = NSDistributedNotificationCenter.defaultCenter()
    observer: UnlockObserver = UnlockObserver.alloc().initWithRunner_(runner)
    center.addObserver_selector_name_object_suspensionBehavior_(
        observer,
        "screenUnlocked:",
        notification_name,
        None,
        NSNotificationSuspensionBehaviorDeliverImmediately,
    )
    logging.info("Listening for %s", notification_name)
    AppHelper.runConsoleEventLoop()


def main() -> int:
    """Start UnlockShortcut."""
    configure_logging()
    try:
        configuration: Configuration = load_configuration()
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        logging.error("Cannot load %s: %s", CONFIG_PATH, error)
        return 2
    try:
        run_event_loop(DailyRunner(configuration), configuration.unlock_notification)
    except KeyboardInterrupt:
        logging.info("Stopped")
    except Exception:
        logging.exception("UnlockShortcut stopped unexpectedly")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
