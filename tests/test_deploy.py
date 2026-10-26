# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
"""Check deployment lifecycle and failure boundaries without sudo or live launchd changes."""

from __future__ import annotations

import plistlib
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
        if "wheel" in arguments:
            if state["fail_build"]:
                raise subprocess.CalledProcessError(1, arguments)
            wheel_directory: Path = Path(arguments[arguments.index("--wheel-dir") + 1])
            (wheel_directory / "unlockshortcut-1.0.0-py3-none-any.whl").touch()
        if "install" in arguments and state["fail_install"]:
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

    assert not any("venv" in command for command in commands)
    build: tuple[str, ...] = next(command for command in commands if "wheel" in command)
    assert build[0] == str(deployment.python)
    installation: tuple[str, ...] = next(command for command in commands if "install" in command)
    assert "--force-reinstall" in installation
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


@pytest.mark.parametrize("failure", ["fail_build", "no_gui"])
def test_preflight_failure_leaves_running_job_untouched(
    environment: tuple[deploy.Deployment, list[tuple[str, ...]], dict[str, bool]], failure: str
) -> None:
    """Build or GUI-domain failures cannot unload the previous daemon or invoke sudo."""
    deployment, commands, state = environment
    state.update(loaded=True)
    state[failure] = True
    with pytest.raises(subprocess.CalledProcessError):
        deploy.deploy(deployment)
    assert state["loaded"]
    assert not any("bootout" in command or "/usr/bin/sudo" in command for command in commands)
    assert not deployment.plist.exists()


def test_failed_install_does_not_publish_plist_or_report_success(
    environment: tuple[deploy.Deployment, list[tuple[str, ...]], dict[str, bool]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Installation errors retain the previous plist and provide recovery instructions."""
    deployment, commands, state = environment
    deploy.replace_plist(deployment.plist, b"previous plist")
    state.update(loaded=True, fail_install=True)
    with pytest.raises(subprocess.CalledProcessError):
        deploy.deploy(deployment)
    assert deployment.plist.read_bytes() == b"previous plist"
    assert not any("bootstrap" in command for command in commands)
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
