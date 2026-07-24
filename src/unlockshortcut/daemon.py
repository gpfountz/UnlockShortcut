"""A launchd-friendly daemon that invokes a Shortcut on the first unlock each day."""

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
    NSDistributedNotificationCenter, # type: ignore[import-not-found]
    NSNotificationSuspensionBehaviorDeliverImmediately, # type: ignore[import-not-found]
    NSObject, # type: ignore[import-not-found]
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

    shortcut_name: str
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


def load_configuration(path: Path = CONFIG_PATH) -> Configuration:
    """Load and validate the daemon configuration."""
    with path.open("rb") as config_file:
        values: dict[str, object] = tomllib.load(config_file)
    return Configuration(
        shortcut_name=_required_text(values, "shortcut_name"),
        unlock_notification=_optional_text(
            values, "unlock_notification", DEFAULT_UNLOCK_NOTIFICATION
        ),
    )


class DailyRunner:
    """Runs a configured Shortcut at most once per local calendar day."""

    def __init__(
        self,
        configuration: Configuration,
        state_path: Path = STATE_PATH,
        execute: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._configuration: Configuration = configuration
        self._state_path: Path = state_path
        self._execute: Callable[..., subprocess.CompletedProcess[str]] = execute

    def _completed_today(self, today: str) -> bool:
        try:
            state: dict[str, object] = json.loads(self._state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return False
        except (OSError, json.JSONDecodeError):
            logging.exception("Unable to read state file; retrying the Shortcut")
            return False
        return state.get("completed_date") == today

    def _record_completion(self, today: str) -> None:
        self._state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary_path: Path = self._state_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps({"completed_date": today}) + "\n", encoding="utf-8")
        temporary_path.replace(self._state_path)

    def handle_unlock(self) -> None:
        """Run the Shortcut if no successful run has been recorded today."""
        today: str = date.today().isoformat()
        if self._completed_today(today):
            logging.info("Screen unlocked; Shortcut already completed today")
            return

        logging.info("Screen unlocked; running Shortcut %r", self._configuration.shortcut_name)
        result: subprocess.CompletedProcess[str] = self._execute(
            [SHORTCUTS_EXECUTABLE, "run", self._configuration.shortcut_name],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            logging.error("Shortcut failed (exit %s): %s", result.returncode, result.stderr.strip())
            return
        self._record_completion(today)
        logging.info("Shortcut completed successfully")


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
        objc.super(UnlockObserver, self).init() # type: ignore[import-not-found]
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
