# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.
"""Verify real distributions selected by UNLOCKSHORTCUT_ARTIFACTS, including omitted notices."""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import zipfile
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

import pytest

from unlockshortcut import __version__

PROJECT: Path = Path(__file__).resolve().parents[1]
RESOURCE_PREFIX: str = "src/unlockshortcut/licenses/"


@pytest.fixture(scope="module")
def artifacts() -> Path:
    """Require actual built wheel and source artifacts for opt-in distribution checks."""
    directory: str | None = os.environ.get("UNLOCKSHORTCUT_ARTIFACTS")
    if directory is None:
        pytest.skip("Set UNLOCKSHORTCUT_ARTIFACTS to the output of python -m build")
    path: Path = Path(directory).resolve()
    assert path.is_dir(), f"Build directory does not exist: {path}"
    return path


@pytest.fixture(scope="module")
def wheel(artifacts: Path) -> Path:
    """Select the actual wheel matching the application's shared version."""
    path: Path = artifacts / f"unlockshortcut-{__version__}-py3-none-any.whl"
    assert path.is_file(), f"Missing build artifact: {path}"
    return path


@pytest.fixture(scope="module")
def wheel_payload(wheel: Path) -> dict[str, bytes]:
    """Load the produced wheel without importing its code or installing dependencies."""
    with zipfile.ZipFile(wheel) as archive:
        return {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}


def verify_wheel_legal_payload(payload: dict[str, bytes]) -> None:
    """Require metadata, metadata license copies, and importable offline resources to agree."""
    prefix: str = f"unlockshortcut-{__version__}.dist-info/"
    metadata: Message = BytesParser().parsebytes(payload[prefix + "METADATA"])
    assert metadata["License-Expression"] == "GPL-3.0-only"
    assert metadata["Version"] == __version__
    assert metadata["Author"] == "Greg Pfountz"
    canonical: bytes = (PROJECT / "LICENSE").read_bytes()
    assert payload[prefix + "licenses/LICENSE"] == canonical
    assert payload["unlockshortcut/licenses/LICENSE"] == canonical
    for name in metadata.get_all("License-File", []):
        assert payload[prefix + "licenses/" + name] == (PROJECT / name).read_bytes()
    resource: Path
    for resource in (PROJECT / RESOURCE_PREFIX).rglob("*"):
        if resource.is_file():
            relative: str = resource.relative_to(PROJECT / "src").as_posix()
            assert payload[relative] == resource.read_bytes()
    assert not any(name.endswith((".so", ".dylib", ".dll")) for name in payload)
    assert all(name.startswith(("unlockshortcut/", prefix)) for name in payload)


def test_built_wheel_contains_legal_payload(wheel_payload: dict[str, bytes]) -> None:
    """The real wheel includes the application license and unchanged upstream notices."""
    verify_wheel_legal_payload(wheel_payload)


@pytest.mark.parametrize(
    "missing",
    [
        "unlockshortcut/licenses/LICENSE",
        "unlockshortcut/licenses/THIRD_PARTY_NOTICES.md",
        "unlockshortcut/licenses/third-party/PyObjC-LICENSE.txt",
        "metadata-license",
    ],
)
def test_build_omissions_are_detected(wheel_payload: dict[str, bytes], missing: str) -> None:
    """Removing any required license from a built wheel makes artifact verification fail."""
    damaged: dict[str, bytes] = wheel_payload.copy()
    name: str = (
        f"unlockshortcut-{__version__}.dist-info/licenses/LICENSE"
        if missing == "metadata-license"
        else missing
    )
    del damaged[name]
    with pytest.raises((KeyError, AssertionError)):
        verify_wheel_legal_payload(damaged)


@pytest.mark.parametrize("option", ["--license", "--third-party-notices", "--version"])
def test_extracted_wheel_exposes_offline_information(
    wheel: Path, tmp_path: Path, option: str
) -> None:
    """Use the actual registered console entry point in an extracted wheel outside the checkout."""
    extraction: Path = tmp_path / "extracted"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(extraction)
    code: str = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from importlib.metadata import distribution
import unlockshortcut.cli
assert Path(unlockshortcut.cli.__file__).resolve().is_relative_to(Path(sys.argv[1]))
package = distribution('unlockshortcut')
entry = next(entry for entry in package.entry_points if entry.name == 'unlockshortcut')
sys.argv = ['unlockshortcut', sys.argv[2]]
try:
    status: int = entry.load()()
except SystemExit as error:
    status = error.code
assert 'Foundation' not in sys.modules and 'objc' not in sys.modules
raise SystemExit(status)
"""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-I", "-c", code, str(extraction), option],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    if option == "--license":
        assert result.stdout.endswith((PROJECT / "LICENSE").read_text())
    elif option == "--third-party-notices":
        assert result.stdout.endswith(
            (PROJECT / RESOURCE_PREFIX / "third-party/PyObjC-LICENSE.txt").read_text()
        )
    else:
        assert result.stdout.strip() == f"unlockshortcut {__version__}"


def test_built_source_archive_contains_complete_project_materials(artifacts: Path) -> None:
    """The real source archive preserves scripts, tests, installation materials, and legal files."""
    path: Path = artifacts / f"unlockshortcut-{__version__}.tar.gz"
    with tarfile.open(path) as archive:
        payload: dict[str, bytes] = {}
        member: tarfile.TarInfo
        for member in archive.getmembers():
            if member.isfile():
                stream = archive.extractfile(member)
                assert stream is not None
                payload[member.name.split("/", maxsplit=1)[1]] = stream.read()
    required: list[Path] = [
        PROJECT / name
        for name in (
            "LICENSE",
            "COPYRIGHT.md",
            "CONTRIBUTING.md",
            "README.md",
            "AGENTS.md",
            "pyproject.toml",
            "MANIFEST.in",
            ".gitattributes",
            ".gitignore",
            "config.example.toml",
            "launchd/com.pfountz.unlockshortcut.plist",
        )
    ]
    for directory in ("src", "scripts", "tests"):
        required.extend((PROJECT / directory).rglob("*.py"))
    required.extend(path for path in (PROJECT / RESOURCE_PREFIX).rglob("*") if path.is_file())
    for source in required:
        relative: str = source.relative_to(PROJECT).as_posix()
        assert payload[relative] == source.read_bytes(), f"Missing or altered source: {relative}"
    metadata: Message = BytesParser().parsebytes(payload["PKG-INFO"])
    assert metadata["License-Expression"] == "GPL-3.0-only"
