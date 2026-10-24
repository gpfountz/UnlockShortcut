# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.
"""Exercise legal commands, resource failures, and exact upstream notice preservation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from unlockshortcut import __version__, cli, daemon, legal

PROJECT: Path = Path(__file__).resolve().parents[1]
RESOURCES: Path = PROJECT / "src/unlockshortcut/licenses"


def test_license_command_includes_attribution_and_complete_license(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The legal command supplies the full canonical license and clear project attribution."""
    assert cli.main(["--license"]) == 0
    output: str = capsys.readouterr().out
    assert "Copyright © 2026 Greg Pfountz" in output
    assert "GPL-3.0-only" in output
    assert "ABSOLUTELY NO WARRANTY" in output
    assert output.endswith((PROJECT / "LICENSE").read_text(encoding="utf-8"))


def test_third_party_command_includes_complete_upstream_notice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dependency notices retain the complete upstream attribution and permission text."""
    assert cli.main(["--third-party-notices"]) == 0
    output: str = capsys.readouterr().out
    assert "pyobjc-framework-Cocoa" in output and "pyobjc-core" in output
    assert output.endswith((RESOURCES / "third-party/PyObjC-LICENSE.txt").read_text())


@pytest.mark.parametrize("content", [None, b"", b"\xff"])
def test_unreadable_license_reports_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    content: bytes | None,
) -> None:
    """Missing, empty, and corrupt packaged licenses produce an actionable error, not success."""
    directory: Path = tmp_path / "licenses"
    directory.mkdir()
    if content is not None:
        (directory / "LICENSE").write_bytes(content)

    def resource_root(_package: str) -> Path:
        """Return the incomplete extracted package used by this failure case."""
        return tmp_path

    monkeypatch.setattr(legal, "files", resource_root)
    assert cli.main(["--license"]) == 2
    output: str
    error: str
    output, error = capsys.readouterr()
    assert output == ""
    assert "LICENSE" in error and "reinstall the package" in error


def test_missing_dependency_license_fails_instead_of_showing_partial_notices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An omitted upstream notice makes the dependency command fail without partial output."""
    directory: Path = tmp_path / "licenses"
    directory.mkdir()
    (directory / "THIRD_PARTY_NOTICES.md").write_text("Dependency overview\n", encoding="utf-8")

    def resource_root(_package: str) -> Path:
        """Return an extracted package whose upstream license was omitted."""
        return tmp_path

    monkeypatch.setattr(legal, "files", resource_root)
    assert cli.main(["--third-party-notices"]) == 2
    output: str
    error: str
    output, error = capsys.readouterr()
    assert not output
    assert "PyObjC-LICENSE.txt" in error


def test_no_arguments_preserves_daemon_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """The unchanged LaunchAgent invocation still delegates to the daemon and propagates status."""
    calls: list[str] = []

    def run_daemon() -> int:
        """Record delegation without starting a real notification loop or writing state."""
        calls.append("daemon")
        return 7

    monkeypatch.setattr(daemon, "main", run_daemon)
    assert cli.main([]) == 7
    assert calls == ["daemon"]


@pytest.mark.parametrize("option", ["--license", "--third-party-notices", "--version", "--help"])
def test_information_commands_do_not_load_cocoa_or_depend_on_working_directory(
    option: str, tmp_path: Path
) -> None:
    """Information remains available before daemon imports and outside the source directory."""
    code: str = """
import sys
sys.path.insert(0, sys.argv[1])
from unlockshortcut.cli import main
try:
    status: int = main(sys.argv[2:])
except SystemExit as error:
    status = error.code
assert 'Foundation' not in sys.modules and 'objc' not in sys.modules
raise SystemExit(status)
"""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-I", "-c", code, str(PROJECT / "src"), option],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout
    if option == "--version":
        assert result.stdout.strip() == f"unlockshortcut {__version__}"


def test_canonical_license_and_snapshots_are_preserved() -> None:
    """The runtime GPL copy and unchanged upstream snapshot retain their recorded bytes."""
    canonical: bytes = (PROJECT / "LICENSE").read_bytes()
    assert canonical == (RESOURCES / "LICENSE").read_bytes()
    assert hashlib.sha256(canonical).hexdigest() == (
        "fb981668c18a279e285fc4d83fba1e836cc84dd4daa73c9697d3cfd2d8aca6e0"
    )
    provenance: dict[str, object] = json.loads(
        (RESOURCES / "third-party/provenance.json").read_text(encoding="utf-8")
    )
    notice: object = provenance["notice"]
    assert isinstance(notice, dict)
    snapshot: bytes = (RESOURCES / "third-party/PyObjC-LICENSE.txt").read_bytes()
    assert hashlib.sha256(snapshot).hexdigest() == notice["sha256"]
    assert b"Ronald Oussoren" in snapshot
    assert b"Greg Pfountz" not in snapshot


def test_package_configuration_retains_shared_version_and_declares_legal_payload() -> None:
    """The real package configuration exposes the CLI and includes all legal-resource classes."""
    configuration: dict[str, object] = tomllib.loads((PROJECT / "pyproject.toml").read_text())
    project: object = configuration["project"]
    assert isinstance(project, dict)
    assert project["license"] == "GPL-3.0-only"
    assert project["dynamic"] == ["version"]
    assert project["scripts"]["unlockshortcut"] == "unlockshortcut.cli:main"
    for pattern in project["license-files"]:
        assert list(PROJECT.glob(pattern)), f"Declared license glob is empty: {pattern}"
