# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
"""Install or update UnlockShortcut and reload its per-user macOS LaunchAgent."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shlex
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
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


def dependency_requirements(project: Path) -> list[str]:
    """Read the existing build and runtime constraints without rewriting or relaxing them."""
    with (project / "pyproject.toml").open("rb") as stream:
        settings: dict[str, object] = tomllib.load(stream)
    build: object = settings.get("build-system")
    application: object = settings.get("project")
    if not isinstance(build, dict) or not isinstance(application, dict):
        raise ValueError("pyproject.toml must declare build-system and project requirements")
    requirements: list[str] = []
    group: object
    for group in (build.get("requires"), application.get("dependencies")):
        if not isinstance(group, list) or not all(isinstance(item, str) for item in group):
            raise ValueError("Build and runtime requirements must be lists of strings")
        requirements.extend(group)
    return requirements


def check_licenses(project: Path) -> None:
    """Apply the existing canonical-license and recorded upstream-notice integrity checks."""
    resources: Path = project / "src/unlockshortcut/licenses"
    canonical: bytes = (project / "LICENSE").read_bytes()
    if (
        canonical != (resources / "LICENSE").read_bytes()
        or hashlib.sha256(canonical).hexdigest()
        != "fb981668c18a279e285fc4d83fba1e836cc84dd4daa73c9697d3cfd2d8aca6e0"
    ):
        raise ValueError("Canonical GPL license integrity check failed")
    provenance: dict[str, object] = json.loads(
        (resources / "third-party/provenance.json").read_text(encoding="utf-8")
    )
    notice: object = provenance.get("notice")
    snapshot: bytes = (resources / "third-party/PyObjC-LICENSE.txt").read_bytes()
    if not isinstance(notice, dict) or hashlib.sha256(snapshot).hexdigest() != notice.get("sha256"):
        raise ValueError("Upstream PyObjC notice integrity check failed")


def prepare_dependencies(deployment: Deployment, directory: Path) -> Path:
    """Install declared requirements in an isolated venv matching the deployment Python."""
    interpreter: str = str(deployment.python) if deployment.python.exists() else sys.executable
    environment: Path = directory / "environment"
    python: Path = environment / "bin/python"
    wheels: Path = directory / "wheels"
    wheels.mkdir()
    print(
        "Preparing isolated dependencies from pyproject.toml (keeping its constraints).", flush=True
    )
    run(interpreter, "-m", "venv", str(environment))
    requirements: list[str] = dependency_requirements(deployment.project)
    run(
        str(python),
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "--dest",
        str(wheels),
        *requirements,
    )
    run(
        str(python),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(wheels),
        *requirements,
    )
    print(
        "Checking dependency consistency, license integrity, and source legal commands.", flush=True
    )
    run(str(python), "-m", "pip", "check")
    check_licenses(deployment.project)
    option: str
    for option in ("--version", "--license", "--third-party-notices"):
        run(
            str(python),
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv.pop(1)); "
            "from unlockshortcut.cli import main; raise SystemExit(main())",
            str(deployment.project / "src"),
            option,
            capture=True,
        )
    return python


def build_wheels(deployment: Deployment, directory: Path, python: Path) -> Path:
    """Build with validated requirements, with no second resolver or isolated build download."""
    print("Building UnlockShortcut with the validated dependencies.", flush=True)
    run(
        str(python),
        "-m",
        "pip",
        "wheel",
        str(deployment.project),
        "--wheel-dir",
        str(directory),
        "--no-build-isolation",
        "--no-deps",
    )
    wheels: list[Path] = list(directory.glob("unlockshortcut-*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"Expected one UnlockShortcut wheel; found {len(wheels)}")
    return wheels[0]


def validate_wheel(deployment: Deployment, wheel: Path, python: Path) -> None:
    """Check the built package and configuration before modifying any installed files."""
    print("Validating the built application and configuration before deployment.", flush=True)
    run(str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel))
    validate_environment(deployment, python)


def validate_environment(deployment: Deployment, python: Path) -> None:
    """Check dependencies, offline commands, and configuration without starting the daemon."""
    run(str(python), "-m", "pip", "check")
    option: str
    for option in ("--version", "--license", "--third-party-notices"):
        run(str(python.parent / "unlockshortcut"), option, capture=True)
    configuration: Path = deployment.configuration_directory / "config.toml"
    if not configuration.exists():
        configuration = deployment.project / "config.example.toml"
    run(
        str(python),
        "-I",
        "-c",
        "import sys; from pathlib import Path; "
        "from unlockshortcut.daemon import load_configuration; "
        "load_configuration(Path(sys.argv[1]))",
        str(configuration),
        capture=True,
    )


def install_wheel(deployment: Deployment, wheel: Path, python: Path) -> None:
    """Install offline into a fresh venv, restoring the previous one on validation failure."""
    environment: Path = deployment.installation / ".venv"
    backup: Path = deployment.installation / f".venv-backup-{uuid.uuid4().hex}"
    existing: bool = environment.exists() or environment.is_symlink()
    run("/usr/bin/sudo", "/bin/mkdir", "-p", str(deployment.installation))
    if existing:
        run("/usr/bin/sudo", "/bin/mv", str(environment), str(backup))
    try:
        run("/usr/bin/sudo", str(python), "-m", "venv", str(environment))
        install_prepared_wheel(deployment, wheel)
    except (OSError, ValueError, subprocess.CalledProcessError):
        run("/usr/bin/sudo", "/bin/rm", "-rf", str(environment))
        if existing:
            run("/usr/bin/sudo", "/bin/mv", str(backup), str(environment))
            print("Restored the previous application environment.", flush=True)
        raise
    if existing:
        cleanup: subprocess.CompletedProcess[str] = run(
            "/usr/bin/sudo", "/bin/rm", "-rf", str(backup), check=False
        )
        if cleanup.returncode:
            print(
                f"Application installed; could not remove environment backup: {backup}", flush=True
            )


def install_prepared_wheel(deployment: Deployment, wheel: Path) -> None:
    """Install only the prepared wheel set and verify the dedicated runtime environment."""
    print("Installing the prepared application and dependencies offline.", flush=True)
    run(
        "/usr/bin/sudo",
        str(deployment.python),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(wheel.parent),
        "--force-reinstall",
        str(wheel),
    )
    validate_environment(deployment, deployment.python)


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
        python: Path = prepare_dependencies(deployment, Path(directory))
        wheel: Path = build_wheels(deployment, Path(directory) / "wheels", python)
        validate_wheel(deployment, wheel, python)
        print("Preflight passed; updating the installed application and LaunchAgent.", flush=True)
        run("/usr/bin/sudo", "-v")
        prepare_configuration(deployment)
        loaded: bool = (
            run(LAUNCHCTL, "print", deployment.service, capture=True, check=False).returncode == 0
        )
        if loaded:
            run(LAUNCHCTL, "bootout", deployment.service)
        installed: bool = False
        try:
            install_wheel(deployment, wheel, python)
            installed = True
            replace_plist(deployment.plist, contents)
            run(LAUNCHCTL, "enable", deployment.service)
            run(LAUNCHCTL, "bootstrap", deployment.domain, str(deployment.plist))
            time.sleep(1)
            status: str = run(LAUNCHCTL, "print", deployment.service, capture=True).stdout
            if not any(line.strip() == "state = running" for line in status.splitlines()):
                raise ValueError("LaunchAgent did not stay running; inspect the logs")
        except (OSError, ValueError, subprocess.CalledProcessError):
            if not installed and loaded and deployment.python.exists():
                run(LAUNCHCTL, "bootstrap", deployment.domain, str(deployment.plist))
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
            "installation requests sudo. Synchronizes pyproject.toml dependencies and "
            "validates them before building. Requires Python 3.11+."
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
