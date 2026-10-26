# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
"""Install or update UnlockShortcut and reload its per-user macOS LaunchAgent."""

from __future__ import annotations

import argparse
import os
import plistlib
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT: Path = Path(__file__).resolve().parents[1]
LABEL: str = "com.pfountz.unlockshortcut"
LAUNCHCTL: str = "/bin/launchctl"


@dataclass(frozen=True)
class Deployment:
    """Paths and launchd targets belonging to the invoking GUI user."""

    project: Path
    home: Path
    uid: int
    installation: Path = Path("/usr/local/UnlockStorage")

    @property
    def python(self) -> Path:
        """Return the dedicated deployment interpreter."""
        return self.installation / ".venv/bin/python"

    @property
    def executable(self) -> Path:
        """Return the installed console entry point."""
        return self.installation / ".venv/bin/unlockshortcut"

    @property
    def configuration_directory(self) -> Path:
        """Return the existing per-user configuration and state directory."""
        return self.home / ".config/UnlockShortcut"

    @property
    def plist(self) -> Path:
        """Return the per-user LaunchAgent destination."""
        return self.home / "Library/LaunchAgents" / f"{LABEL}.plist"

    @property
    def domain(self) -> str:
        """Return the current user's GUI login domain."""
        return f"gui/{self.uid}"

    @property
    def service(self) -> str:
        """Return the full launchd service target."""
        return f"{self.domain}/{LABEL}"

    def mode(self) -> str:
        """Treat an existing environment or plist as an update, including partial installs."""
        return "update" if self.python.exists() or self.plist.exists() else "new installation"


def run(
    *arguments: str, capture: bool = False, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Execute an argument vector without a shell and propagate actionable failures."""
    return subprocess.run(arguments, text=True, capture_output=capture, check=check)


def render_plist(deployment: Deployment) -> bytes:
    """Preserve template settings while adapting executable and log paths to this user."""
    template: Path = deployment.project / "launchd" / f"{LABEL}.plist"
    with template.open("rb") as stream:
        settings: dict[str, object] = plistlib.load(stream)
    if settings.get("Label") != LABEL:
        raise ValueError(f"The LaunchAgent template must use Label {LABEL!r}")
    arguments: object = settings.get("ProgramArguments")
    if not isinstance(arguments, list) or not arguments:
        raise ValueError("The LaunchAgent template needs nonempty ProgramArguments")
    settings["ProgramArguments"] = [str(deployment.executable), *arguments[1:]]
    settings["StandardOutPath"] = str(deployment.configuration_directory / "launchd.out.log")
    settings["StandardErrorPath"] = str(deployment.configuration_directory / "launchd.err.log")
    notices: bytes = (
        b"<!-- SPDX-FileCopyrightText: 2026 Greg Pfountz -->\n"
        b"<!-- SPDX-License-Identifier: GPL-3.0-only -->\n"
    )
    return plistlib.dumps(settings, sort_keys=False).replace(b"<plist", notices + b"<plist", 1)


def prepare_configuration(deployment: Deployment) -> None:
    """Create private defaults only when absent, preserving configuration, state, and logs."""
    directory: Path = deployment.configuration_directory
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    configuration: Path = directory / "config.toml"
    if not configuration.exists():
        defaults: bytes = (deployment.project / "config.example.toml").read_bytes()
        descriptor: int = os.open(configuration, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(defaults)


def build_wheels(deployment: Deployment, directory: Path) -> Path:
    """Build the application and download dependency wheels before stopping the daemon."""
    interpreter: str = str(deployment.python) if deployment.python.exists() else sys.executable
    run(
        interpreter,
        "-m",
        "pip",
        "wheel",
        str(deployment.project),
        "--wheel-dir",
        str(directory),
    )
    wheels: list[Path] = list(directory.glob("unlockshortcut-*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"Expected one UnlockShortcut wheel; found {len(wheels)}")
    return wheels[0]


def install_wheel(deployment: Deployment, wheel: Path) -> None:
    """Install into the dedicated environment, including updates with an unchanged version."""
    run("/usr/bin/sudo", "/bin/mkdir", "-p", str(deployment.installation))
    if not deployment.python.exists():
        run("/usr/bin/sudo", sys.executable, "-m", "venv", str(deployment.installation / ".venv"))
    run(
        "/usr/bin/sudo",
        str(deployment.python),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(wheel.parent),
        "--upgrade",
        "--force-reinstall",
        str(wheel),
    )
    run(str(deployment.python), "-m", "pip", "check")
    option: str
    for option in ("--version", "--license", "--third-party-notices"):
        run(str(deployment.executable), option, capture=True)
    run(
        str(deployment.python),
        "-I",
        "-c",
        "from unlockshortcut.daemon import load_configuration; load_configuration()",
        capture=True,
    )


def replace_plist(destination: Path, contents: bytes) -> None:
    """Atomically replace the installed plist with standard per-user read permissions."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
        temporary: Path = Path(stream.name)
        try:
            stream.write(contents)
            stream.flush()
            temporary.chmod(0o644)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def deploy(deployment: Deployment) -> None:
    """Perform an install or update and load the resulting job in this GUI login session."""
    if sys.platform != "darwin":
        raise ValueError("Deployment requires macOS")
    if os.getuid() == 0:
        raise ValueError("Run scripts/deploy.sh as your GUI user, without sudo")
    if sys.version_info < (3, 11):  # noqa: UP036 -- the wrapper can select a system Python
        raise ValueError("Deployment requires Python 3.11 or newer")
    run(LAUNCHCTL, "print", deployment.domain, capture=True)
    contents: bytes = render_plist(deployment)
    print(f"UnlockShortcut deployment: {deployment.mode()}", flush=True)
    print(f"Application: {deployment.installation}\nLaunchAgent: {deployment.plist}", flush=True)
    with tempfile.TemporaryDirectory(prefix="unlockshortcut-deploy-") as directory:
        wheel: Path = build_wheels(deployment, Path(directory))
        run("/usr/bin/sudo", "-v")
        prepare_configuration(deployment)
        loaded: bool = (
            run(LAUNCHCTL, "print", deployment.service, capture=True, check=False).returncode == 0
        )
        if loaded:
            run(LAUNCHCTL, "bootout", deployment.service)
        try:
            install_wheel(deployment, wheel)
            replace_plist(deployment.plist, contents)
            run(LAUNCHCTL, "enable", deployment.service)
            run(LAUNCHCTL, "bootstrap", deployment.domain, str(deployment.plist))
            time.sleep(1)
            status: str = run(LAUNCHCTL, "print", deployment.service, capture=True).stdout
            if not any(line.strip() == "state = running" for line in status.splitlines()):
                raise ValueError("LaunchAgent did not stay running; inspect the logs")
        except (OSError, ValueError, subprocess.CalledProcessError):
            print(
                "Deployment failed; the daemon may be stopped. Correct the error and rerun "
                "scripts/deploy.sh.\n"
                f"Logs: {deployment.configuration_directory}",
                file=sys.stderr,
            )
            raise
    version: str = run(str(deployment.executable), "--version", capture=True).stdout.strip()
    print(f"Deployed {version}; running in {deployment.domain}.")


def main() -> int:
    """Parse help and report deployment failures without a Python traceback."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=(
            "Install or update UnlockShortcut, apply the repository plist, and load it "
            "for the current GUI login session. Run without sudo; only application "
            "installation requests sudo. Requires Python 3.11+."
        )
    )
    parser.parse_args()
    try:
        deploy(Deployment(PROJECT, Path.home(), os.getuid()))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Deployment error: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            if error.stderr:
                print(error.stderr.strip(), file=sys.stderr)
            print(f"Failed command: {shlex.join(error.cmd)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
