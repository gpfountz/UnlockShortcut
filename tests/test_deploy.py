# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
"""Check deployment lifecycle and failure boundaries without sudo or live launchd changes."""

from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import deploy


@pytest.fixture
def environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[deploy.Deployment, list[tuple[str, ...]], dict[str, bool]]:
    """Redirect installation paths and simulate every external deployment command."""
    deployment: deploy.Deployment = deploy.Deployment(
        deploy.PROJECT, tmp_path / "home with spaces", 501, tmp_path / "installed app"
    )
    commands: list[tuple[str, ...]] = []
    state: dict[str, bool] = {
        "loaded": False,
        "fail_build": False,
        "fail_download": False,
        "fail_dependencies": False,
        "fail_dependency_check": False,
        "fail_source_legal": False,
        "fail_wheel_validation": False,
        "fail_configuration": False,
        "fail_final_check": False,
        "fail_install": False,
        "fail_startup": False,
        "no_gui": False,
    }

    def fake_run(
        *arguments: str, capture: bool = False, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Model wheel creation, job loading, and injected failures while recording order."""
        commands.append(arguments)
        output: str = ""
        status: int = 0
        if "venv" in arguments:
            python: Path = Path(arguments[-1]) / "bin/python"
            python.parent.mkdir(parents=True)
            python.touch()
        if arguments[:2] == ("/usr/bin/sudo", "/bin/mv"):
            shutil.move(arguments[2], arguments[3])
        if arguments[:3] == ("/usr/bin/sudo", "/bin/rm", "-rf"):
            shutil.rmtree(arguments[3], ignore_errors=True)
        if "download" in arguments and state["fail_download"]:
            raise subprocess.CalledProcessError(1, arguments)
        if "wheel" in arguments:
            if state["fail_build"]:
                raise subprocess.CalledProcessError(1, arguments)
            wheel_directory: Path = Path(arguments[arguments.index("--wheel-dir") + 1])
            (wheel_directory / "unlockshortcut-1.0.0-py3-none-any.whl").touch()
        if "install" in arguments:
            failed: bool = (
                state["fail_install"]
                if arguments[0] == "/usr/bin/sudo"
                else state["fail_wheel_validation"]
                if "--no-deps" in arguments
                else state["fail_dependencies"]
            )
            if failed:
                raise subprocess.CalledProcessError(1, arguments)
        if "check" in arguments:
            failed = (
                state["fail_final_check"]
                if arguments[0] == str(deployment.python)
                else state["fail_dependency_check"]
            )
            if failed:
                raise subprocess.CalledProcessError(1, arguments)
        if "--license" in arguments and "-c" in arguments and state["fail_source_legal"]:
            raise subprocess.CalledProcessError(1, arguments)
        if "-c" in arguments and "load_configuration" in arguments[-2]:
            if state["fail_configuration"]:
                raise subprocess.CalledProcessError(1, arguments)
        if arguments[:2] == (deploy.LAUNCHCTL, "print"):
            if arguments[2] == deployment.domain:
                status = 1 if state["no_gui"] else 0
            else:
                status = 0 if state["loaded"] else 113
                output = "state = exited\n" if state["fail_startup"] else "state = running\n"
        if arguments[:2] == (deploy.LAUNCHCTL, "bootout"):
            state["loaded"] = False
        if arguments[:2] == (deploy.LAUNCHCTL, "bootstrap"):
            state["loaded"] = True
        if "--version" in arguments:
            output = "unlockshortcut 1.0.0\n"
        if check and status:
            raise subprocess.CalledProcessError(status, arguments)
        return subprocess.CompletedProcess(arguments, status, stdout=output, stderr="")

    monkeypatch.setattr(deploy, "run", fake_run)
    monkeypatch.setattr("scripts.deploy.sys.platform", "darwin")
    monkeypatch.setattr("scripts.deploy.os.getuid", lambda: 501)
    monkeypatch.setattr("scripts.deploy.time.sleep", lambda _seconds: None)
    return deployment, commands, state


def test_new_install_loads_current_gui_session(
    environment: tuple[deploy.Deployment, list[tuple[str, ...]], dict[str, bool]],
) -> None:
    """A first install creates defaults and a venv and bootstraps the correct GUI domain."""
    deployment, commands, state = environment
    assert deployment.mode() == "new installation"
    deploy.deploy(deployment)

    assert any("venv" in command for command in commands)
    assert (deploy.LAUNCHCTL, "bootstrap", "gui/501", str(deployment.plist)) in commands
    assert not any("bootout" in command for command in commands)
    assert state["loaded"]
    configuration: Path = deployment.configuration_directory / "config.toml"
    assert configuration.read_bytes() == (deploy.PROJECT / "config.example.toml").read_bytes()
    assert configuration.stat().st_mode & 0o777 == 0o600
    assert deployment.configuration_directory.stat().st_mode & 0o777 == 0o700
    assert deployment.plist.stat().st_mode & 0o777 == 0o644
    assert b"SPDX-License-Identifier: GPL-3.0-only" in deployment.plist.read_bytes()
    settings: dict[str, object] = plistlib.loads(deployment.plist.read_bytes())
    assert settings["ProgramArguments"] == [str(deployment.executable)]
    assert settings["StandardErrorPath"] == str(
        deployment.configuration_directory / "launchd.err.log"
    )


@pytest.mark.parametrize("loaded", [True, False])
def test_update_preserves_user_files_and_restarts_job(
    environment: tuple[deploy.Deployment, list[tuple[str, ...]], dict[str, bool]], loaded: bool
) -> None:
    """Loaded and unloaded existing installations update without losing daily progress."""
    deployment, commands, state = environment
    deployment.python.parent.mkdir(parents=True)
    deployment.python.touch()
    deployment.configuration_directory.mkdir(parents=True)
    name: str
    for name in ("config.toml", "state.json", "unlockshortcut.log"):
        (deployment.configuration_directory / name).write_text(f"existing {name}\n")
    deploy.replace_plist(deployment.plist, b"old plist")
    state["loaded"] = loaded
    assert deployment.mode() == "update"

    deploy.deploy(deployment)

    preparation: tuple[str, ...] = next(command for command in commands if "venv" in command)
    assert preparation[0] == str(deployment.python)
    build: tuple[str, ...] = next(command for command in commands if "wheel" in command)
    assert build[0] != str(deployment.python)
    assert "environment/bin/python" in build[0]
    assert "--no-build-isolation" in build and "--no-deps" in build
    installation: tuple[str, ...] = next(
        command for command in commands if "install" in command and command[0] == "/usr/bin/sudo"
    )
    assert "--force-reinstall" in installation
    assert "--no-index" in installation
    bootstrap: tuple[str, ...] = (
        deploy.LAUNCHCTL,
        "bootstrap",
        deployment.domain,
        str(deployment.plist),
    )
    assert commands.index(installation) < commands.index(bootstrap)
    if loaded:
        bootout: tuple[str, ...] = (deploy.LAUNCHCTL, "bootout", deployment.service)
        assert commands.index(build) < commands.index(bootout) < commands.index(installation)
    else:
        assert not any("bootout" in command for command in commands)
    for name in ("config.toml", "state.json", "unlockshortcut.log"):
        assert (deployment.configuration_directory / name).read_text() == f"existing {name}\n"
    assert plistlib.loads(deployment.plist.read_bytes())["RunAtLoad"] is True


def test_plist_template_changes_survive_rendering(tmp_path: Path) -> None:
    """Reloaded templates retain custom launchd settings and additional daemon arguments."""
    template: Path = tmp_path / "launchd" / f"{deploy.LABEL}.plist"
    template.parent.mkdir()
    template.write_bytes(
        plistlib.dumps(
            {
                "Label": deploy.LABEL,
                "ProgramArguments": ["/old/executable", "--example"],
                "ThrottleInterval": 30,
            }
        )
    )
    deployment: deploy.Deployment = deploy.Deployment(tmp_path, tmp_path / "user", 123)
    settings: dict[str, object] = plistlib.loads(deploy.render_plist(deployment))
    assert settings["ThrottleInterval"] == 30
    assert settings["ProgramArguments"] == [str(deployment.executable), "--example"]


@pytest.mark.parametrize(
    "failure",
    [
        "fail_build",
        "no_gui",
        "fail_download",
        "fail_dependencies",
        "fail_dependency_check",
        "fail_source_legal",
        "fail_wheel_validation",
        "fail_configuration",
    ],
)
def test_preflight_failure_leaves_running_job_untouched(
    environment: tuple[deploy.Deployment, list[tuple[str, ...]], dict[str, bool]], failure: str
) -> None:
    """Preflight failures preserve the installed application, plist, configuration, and job."""
    deployment, commands, state = environment
    deployment.python.parent.mkdir(parents=True)
    deployment.python.write_text("original interpreter")
    deployment.configuration_directory.mkdir(parents=True)
    configuration: Path = deployment.configuration_directory / "config.toml"
    configuration.write_text("original configuration")
    deploy.replace_plist(deployment.plist, b"original plist")
    state.update(loaded=True)
    state[failure] = True
    with pytest.raises(subprocess.CalledProcessError):
        deploy.deploy(deployment)
    assert state["loaded"]
    assert not any("bootout" in command or "/usr/bin/sudo" in command for command in commands)
    assert deployment.python.read_text() == "original interpreter"
    assert deployment.plist.read_bytes() == b"original plist"
    assert configuration.read_text() == "original configuration"
    if failure in {
        "fail_download",
        "fail_dependencies",
        "fail_dependency_check",
        "fail_source_legal",
    }:
        assert not any("wheel" in command for command in commands)


@pytest.mark.parametrize("failure", ["fail_install", "fail_final_check"])
@pytest.mark.parametrize("loaded", [True, False])
def test_failed_install_restores_application_and_previous_job(
    environment: tuple[deploy.Deployment, list[tuple[str, ...]], dict[str, bool]],
    capsys: pytest.CaptureFixture[str],
    failure: str,
    loaded: bool,
) -> None:
    """Offline install or validation errors restore the old venv and its prior loaded state."""
    deployment, commands, state = environment
    deployment.python.parent.mkdir(parents=True)
    deployment.python.write_text("original interpreter")
    marker: Path = deployment.python.parent / "old dependency"
    marker.write_text("old package")
    deploy.replace_plist(deployment.plist, b"previous plist")
    state.update(loaded=loaded)
    state[failure] = True
    with pytest.raises(subprocess.CalledProcessError):
        deploy.deploy(deployment)
    assert deployment.plist.read_bytes() == b"previous plist"
    assert deployment.python.read_text() == "original interpreter"
    assert marker.read_text() == "old package"
    assert state["loaded"] == loaded
    assert any("bootstrap" in command for command in commands) == loaded
    assert not list(deployment.installation.glob(".venv-backup-*"))
    assert "rerun scripts/deploy.sh" in capsys.readouterr().err


def test_immediate_startup_exit_is_a_deployment_failure(
    environment: tuple[deploy.Deployment, list[tuple[str, ...]], dict[str, bool]],
) -> None:
    """A loaded job whose process has exited must not count as a successful deployment."""
    deployment, _commands, state = environment
    state["fail_startup"] = True
    with pytest.raises(ValueError, match="did not stay running"):
        deploy.deploy(deployment)


def test_sudo_invocation_is_rejected_before_mutation(
    environment: tuple[deploy.Deployment, list[tuple[str, ...]], dict[str, bool]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running the whole script as root must never create a root-owned per-user agent."""
    deployment, commands, _state = environment
    monkeypatch.setattr("scripts.deploy.os.getuid", lambda: 0)
    with pytest.raises(ValueError, match="without sudo"):
        deploy.deploy(deployment)
    assert not commands


def test_shell_launcher_help_from_another_directory(tmp_path: Path) -> None:
    """The executable shell entry point locates its helper correctly through spaced paths."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [str(deploy.PROJECT / "scripts/deploy.sh"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "current GUI login session" in result.stdout


def test_dependency_preflight_precedes_build_and_installation(
    environment: tuple[deploy.Deployment, list[tuple[str, ...]], dict[str, bool]],
) -> None:
    """Dependencies and source checks finish before build; wheel checks precede sudo."""
    deployment, commands, _state = environment
    deploy.deploy(deployment)
    download: tuple[str, ...] = next(command for command in commands if "download" in command)
    dependency_install: tuple[str, ...] = next(
        command for command in commands if "install" in command
    )
    check: tuple[str, ...] = next(command for command in commands if "check" in command)
    source_license: tuple[str, ...] = next(
        command for command in commands if "--license" in command
    )
    build: tuple[str, ...] = next(command for command in commands if "wheel" in command)
    artifact_install: tuple[str, ...] = next(
        command for command in commands if "install" in command and "--no-deps" in command
    )
    artifact_legal: tuple[str, ...] = next(
        command for command in commands if "--license" in command and "-c" not in command
    )
    sudo: tuple[str, ...] = next(command for command in commands if command[0] == "/usr/bin/sudo")
    assert commands.index(download) < commands.index(dependency_install) < commands.index(check)
    assert commands.index(check) < commands.index(source_license) < commands.index(build)
    assert commands.index(build) < commands.index(artifact_install) < commands.index(artifact_legal)
    assert commands.index(artifact_legal) < commands.index(sudo)
    assert "--only-binary=:all:" in download
    assert "--no-index" in dependency_install
    assert "--upgrade" not in dependency_install
    requirement: str
    for requirement in deploy.dependency_requirements(deployment.project):
        assert requirement in download and requirement in dependency_install
    assert not any(
        "install" in command and command[0] == str(deployment.project / ".venv/bin/python")
        for command in commands
    )


def test_declared_pins_are_passed_unchanged(tmp_path: Path) -> None:
    """Exact pins and bounded requirements are read verbatim without changing metadata."""
    metadata: Path = tmp_path / "pyproject.toml"
    original: bytes = (
        b'[build-system]\nrequires = ["setuptools==84.2.1"]\n'
        b'[project]\ndependencies = ["example==1.2.3", "other>=2,<3"]\n'
    )
    metadata.write_bytes(original)
    assert deploy.dependency_requirements(tmp_path) == [
        "setuptools==84.2.1",
        "example==1.2.3",
        "other>=2,<3",
    ]
    assert metadata.read_bytes() == original


@pytest.mark.parametrize("resource", ["LICENSE", "third-party/PyObjC-LICENSE.txt"])
def test_license_integrity_failure_stops_before_build(
    environment: tuple[deploy.Deployment, list[tuple[str, ...]], dict[str, bool]],
    tmp_path: Path,
    resource: str,
) -> None:
    """Altered license snapshots abort deployment before building or touching the installed job."""
    original, commands, state = environment
    project: Path = tmp_path / "checkout with spaces"
    shutil.copytree(original.project / "launchd", project / "launchd")
    shutil.copytree(
        original.project / "src/unlockshortcut/licenses", project / "src/unlockshortcut/licenses"
    )
    shutil.copy2(original.project / "LICENSE", project / "LICENSE")
    shutil.copy2(original.project / "pyproject.toml", project / "pyproject.toml")
    (project / "src/unlockshortcut/licenses" / resource).write_text("altered license")
    state["loaded"] = True
    deployment: deploy.Deployment = deploy.Deployment(
        project, original.home, original.uid, original.installation
    )
    with pytest.raises(ValueError, match="integrity check failed"):
        deploy.deploy(deployment)
    assert state["loaded"]
    assert not any("wheel" in command or command[0] == "/usr/bin/sudo" for command in commands)


def test_failed_first_install_removes_partial_environment(
    environment: tuple[deploy.Deployment, list[tuple[str, ...]], dict[str, bool]],
) -> None:
    """A final dependency-install failure on first deployment leaves no incomplete application."""
    deployment, _commands, state = environment
    state["fail_install"] = True
    with pytest.raises(subprocess.CalledProcessError):
        deploy.deploy(deployment)
    assert not (deployment.installation / ".venv").exists()
    assert not deployment.plist.exists()
    assert not state["loaded"]
