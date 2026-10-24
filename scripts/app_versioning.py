# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.
"""Prepare commit-time application versions without closing batches on push attempts."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path

SOURCE: str = "src/unlockshortcut/_version.py"
MANAGED: str = "# Managed by UnlockShortcut app versioning."
ASSIGNMENT: re.Pattern[str] = re.compile(
    r"""(?m)^__version__(?:[ \t]*:[ \t]*str)?[ \t]*=[ \t]*"""
    r"""(?P<quote>["'])(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))"""
    r"""(?P=quote)[ \t]*(?:\#[^\n]*)?$"""
)
FEATURE: re.Pattern[str] = re.compile(r"(?m)^Versioning-Feature: ([0-9a-f]{32})$")


class VersioningError(RuntimeError):
    """An unsafe or ambiguous versioning operation that needs user intervention."""


@dataclass(frozen=True, order=True)
class Version:
    """A strictly parsed application semantic version without build identifiers."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        """Return the package-compatible version string."""
        return f"{self.major}.{self.minor}.{self.patch}"

    def advance(self, feature: bool = False) -> Version:
        """Allocate one minor for a feature, or one patch for a fix batch."""
        if feature:
            return Version(self.major, self.minor + 1, 0)
        return Version(self.major, self.minor, self.patch + 1)


def git(*arguments: str, data: str | None = None, check: bool = True, raw: bool = False) -> str:
    """Run Git against the caller's repository and active index."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", *arguments], input=data, capture_output=True, text=True, check=False
    )
    if check and result.returncode:
        raise VersioningError(result.stderr.strip() or f"git {arguments[0]} failed")
    return result.stdout if raw else result.stdout.rstrip("\n")


def succeeds(*arguments: str) -> bool:
    """Return whether a read-only Git predicate succeeds."""
    result: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["git", *arguments], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    )
    return result.returncode == 0


def setting(key: str, default: str = "") -> str:
    """Read optional clone-local configuration without exposing remote URLs."""
    return git("config", "--get", key, check=False) or default


def read_version(text: str) -> Version:
    """Require one precise version assignment while preserving surrounding source."""
    matches: list[re.Match[str]] = list(ASSIGNMENT.finditer(text))
    if len(matches) != 1:
        raise VersioningError(f"{SOURCE} must contain exactly one semantic __version__ assignment")
    components: list[int] = [int(part) for part in matches[0]["version"].split(".")]
    return Version(*components)


def replace_version(text: str, version: Version) -> str:
    """Replace only version digits, retaining annotations, comments, and formatting."""
    read_version(text)
    match: re.Match[str] | None = ASSIGNMENT.search(text)
    assert match is not None
    return text[: match.start("version")] + str(version) + text[match.end("version") :]


def source_at(revision: str) -> str:
    """Read a historical or staged version source, allowing pre-migration metadata."""
    return git("show", f"{revision}:{SOURCE}", check=False, raw=True)


def version_at(revision: str) -> Version:
    """Read versions on either side of the centralized-source migration."""
    text: str = source_at(revision)
    if text:
        return read_version(text)
    metadata: str = git("show", f"{revision}:pyproject.toml")
    value: object = tomllib.loads(metadata).get("project", {}).get("version")
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise VersioningError(f"Cannot determine application version at {revision}")
    return read_version(f'__version__ = "{value}"')


def branch_name() -> str:
    """Require a branch for allocating new versions; detached replay is handled separately."""
    branch: str = git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if not branch:
        raise VersioningError("Detached HEAD: switch to a branch before allocating a version")
    return branch


def replaying() -> bool:
    """Identify Git-managed rebase replay, which must retain recorded versions."""
    return any(
        Path(git("rev-parse", "--git-path", name)).exists()
        for name in ("rebase-merge", "rebase-apply")
    )


def primary_ref() -> str:
    """Find the primary branch locally or in a new single-branch clone."""
    primary: str = setting("versioning.primary", "main")
    remote: str = setting("versioning.remote", "origin")
    for candidate in (f"refs/heads/{primary}", f"refs/remotes/{remote}/{primary}"):
        if succeeds("rev-parse", "--verify", candidate):
            return candidate
    raise VersioningError(f"Fetch {remote}/{primary} before preparing this branch")


def validate_mapping(branch: str, remote: str) -> None:
    """Refuse configurations whose publication destination differs from the documented one."""
    upstream_remote: str = setting(f"branch.{branch}.remote")
    upstream_ref: str = setting(f"branch.{branch}.merge")
    if upstream_remote and (upstream_remote != remote or upstream_ref != f"refs/heads/{branch}"):
        raise VersioningError(
            f"Expected upstream {remote}/{branch}; "
            "correct the upstream or publication configuration"
        )
    if setting(f"remote.{remote}.push") or setting(f"remote.{remote}.pushurl"):
        raise VersioningError(
            "Custom push refspecs/pushurl need an explicit publication integration"
        )
    if (
        setting("remote.pushDefault", remote) != remote
        or setting(f"branch.{branch}.pushRemote", remote) != remote
    ):
        raise VersioningError(
            "Push remote differs from versioning.remote; align them before committing"
        )
    refspecs: list[str] = git("config", "--get-all", f"remote.{remote}.fetch").splitlines()
    if refspecs != [f"+refs/heads/*:refs/remotes/{remote}/*"]:
        raise VersioningError(
            "Expected the standard remote fetch refspec; repair it before committing"
        )


def publication(branch: str) -> str | None:
    """Query the actual remote branch; never mistake a pre-push attempt for publication."""
    remote: str = setting("versioning.remote", "origin")
    validate_mapping(branch, remote)
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", remote, f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 2:
        return None
    if result.returncode:
        raise VersioningError(f"Cannot verify {remote}/{branch}; restore remote access and retry")
    commit: str = result.stdout.split()[0]
    if not succeeds("cat-file", "-e", f"{commit}^{{commit}}"):
        private_ref: str = f"refs/versioning/publications/{branch}"
        git("fetch", "--no-tags", remote, f"+refs/heads/{branch}:{private_ref}")
        if git("rev-parse", private_ref) != commit:
            raise VersioningError("Publication changed during verification; retry the commit")
    if not succeeds("merge-base", "--is-ancestor", commit, "HEAD"):
        raise VersioningError(
            f"{remote}/{branch} is ahead or divergent; fetch and merge/rebase first"
        )
    return commit


def feature_identity(branch: str) -> str:
    """Recover feature intent from explicit configuration or unique first-parent history."""
    intent: str = setting(f"branch.{branch}.versioningIntent")
    if intent == "fix" or branch == setting("versioning.primary", "main"):
        return ""
    identity: str = setting(f"branch.{branch}.versioningFeature")
    if identity:
        return identity
    return history_feature(branch)


def history_feature(branch: str, ignore_fix: bool = False) -> str:
    """Recover durable branch identity, optionally ignoring a later fix classification."""
    base: str = git("merge-base", "HEAD", primary_ref())
    history: str = git("log", "--first-parent", "--format=%B%x00", "HEAD")
    for message in history.split("\0"):
        if f"Versioning-Branch: {branch}\n" in message:
            if not ignore_fix and "Versioning-Intent: fix\n" in message:
                return ""
            match: re.Match[str] | None = FEATURE.search(message)
            if match:
                return match[1]
    unique_history: str = git("log", "--first-parent", "--format=%B", f"{base}..HEAD")
    match = FEATURE.search(unique_history)
    return match[1] if match else ""


def allocated(identity: str) -> bool:
    """Recognize a feature's successful allocation from committed trailers, not hook attempts."""
    return bool(identity and f"Versioning-Feature: {identity}" in git("log", "--format=%B", "HEAD"))


def expected_version(branch: str, head: Version) -> Version:
    """Compute a branch batch version from verified publication and durable feature identity."""
    published: str | None = publication(branch)
    identity: str = feature_identity(branch)
    if identity and not allocated(identity):
        return head.advance(feature=True)
    if published:
        baseline: Version = version_at(published)
    elif branch != setting("versioning.primary", "main"):
        baseline = version_at(git("merge-base", "HEAD", primary_ref()))
    else:
        root: str = git("rev-list", "--first-parent", "--max-parents=0", "HEAD").splitlines()[-1]
        baseline = version_at(root)
    if head < baseline:
        raise VersioningError("Local version is below its publication baseline; reconcile history")
    if head > baseline:
        return head
    return head.advance()


def meaningful_changes() -> bool:
    """Exclude a leftover version assignment when all real staged changes were removed."""
    paths: list[str] = git("diff", "--cached", "--name-only", "--no-renames", "-z").split("\0")
    paths = [path for path in paths if path]
    if not paths:
        return False
    if paths != [SOURCE] or not source_at("HEAD"):
        return True
    return replace_version(source_at("HEAD"), Version(0, 0, 0)) != replace_version(
        source_at(""), Version(0, 0, 0)
    )


def stage_version(version: Version) -> None:
    """Change only the version field in the active index and preserve unstaged source edits."""
    staged: str = source_at("")
    work_path: Path = Path(SOURCE)
    working: str = work_path.read_text(encoding="utf-8")
    if read_version(working) != read_version(staged):
        raise VersioningError(
            f"Unstaged version edit in {SOURCE}; stage or resolve that field first"
        )
    replacement: str = replace_version(staged, version)
    if replacement == staged:
        return
    update_index(replacement)
    work_path.write_text(replace_version(working, version), encoding="utf-8")


def update_index(source: str) -> None:
    """Write only the shared source blob into the active index without staging other paths."""
    mode: str = git("ls-files", "--stage", "--", SOURCE).split()[0]
    blob: str = git("hash-object", "-w", "--stdin", data=source)
    git("update-index", "--cacheinfo", mode, blob, SOURCE)


def synchronize_index() -> None:
    """Repair Git's main index after selected-file commits using its prior version as a guard."""
    if replaying() or not succeeds("rev-parse", "--verify", "HEAD^"):
        return
    current: Version = version_at("HEAD")
    previous: Version = version_at("HEAD^")
    staged_source: str = source_at("")
    if not staged_source or current <= previous or read_version(staged_source) != previous:
        return
    working: str = Path(SOURCE).read_text(encoding="utf-8")
    if read_version(working) == current:
        update_index(replace_version(staged_source, current))


def prepare(merge: bool = False) -> None:
    """Prepare one commit while preserving merges, replay, empty commits, and partial staging."""
    if replaying() or succeeds("diff", "--cached", "--quiet"):
        return
    head: Version = version_at("HEAD")
    staged: Version = version_at("")
    if merge or succeeds("rev-parse", "--verify", "MERGE_HEAD"):
        if staged.major != head.major and os.environ.get("APP_VERSIONING_ALLOW_MAJOR") != "1":
            raise VersioningError(
                "Merge crosses application majors; reconcile the version explicitly"
            )
        stage_version(max(head, staged))
        return
    if staged < head:
        raise VersioningError("A staged version downgrade is not allowed")
    if staged.major != head.major:
        if os.environ.get("APP_VERSIONING_ALLOW_MAJOR") != "1":
            raise VersioningError(
                "Major change requires explicit approval and APP_VERSIONING_ALLOW_MAJOR=1"
            )
        publication(branch_name())
        stage_version(staged)
        return
    if not meaningful_changes():
        stage_version(head)
        raise VersioningError("Only a leftover version change was staged; restored it to HEAD")
    expected: Version = expected_version(branch_name(), head)
    if staged not in (head, expected):
        raise VersioningError(f"Unexpected staged version {staged}; expected {head} or {expected}")
    stage_version(expected)


def annotate_message(path: Path, source: str) -> None:
    """Record feature identity with a successful commit so retries cannot consume a minor."""
    if replaying() or source in ("merge", "squash") or not meaningful_changes():
        return
    branch: str = branch_name()
    identity: str = feature_identity(branch)
    message: str = path.read_text(encoding="utf-8")
    if not identity and setting(f"branch.{branch}.versioningIntent") != "fix":
        return
    message = FEATURE.sub("", message).rstrip()
    message = re.sub(r"(?m)^Versioning-(?:Branch|Intent):[^\n]*\n?", "", message).rstrip()
    trailers: str = f"Versioning-Branch: {branch}\n"
    trailers += f"Versioning-Feature: {identity}\n" if identity else "Versioning-Intent: fix\n"
    path.write_text(message + "\n\n" + trailers, encoding="utf-8")


def classify(intent: str) -> None:
    """Set explicit feature/fix intent without changing source or allocating a version."""
    branch: str = branch_name()
    if branch == setting("versioning.primary", "main") and intent == "feature":
        raise VersioningError("Create a feature branch before classifying feature work")
    identity: str = setting(f"branch.{branch}.versioningFeature") or history_feature(
        branch, ignore_fix=True
    )
    git("config", "--local", f"branch.{branch}.versioningIntent", intent)
    if intent == "feature":
        git("config", "--local", f"branch.{branch}.versioningFeature", identity or uuid.uuid4().hex)
    print(f"{branch}: {intent}; version will be prepared at commit time")


def merge_driver(base: Path, ours: Path, theirs: Path) -> int:
    """Select the higher compatible version while retaining non-version merge conflicts."""
    contents: list[str] = [path.read_text(encoding="utf-8") for path in (base, ours, theirs)]
    versions: list[Version] = [read_version(content) for content in contents]
    if (
        versions[1].major != versions[2].major
        and os.environ.get("APP_VERSIONING_ALLOW_MAJOR") != "1"
    ):
        raise VersioningError(
            "Version merge crosses majors; resolve explicitly and stage the result"
        )
    with tempfile.TemporaryDirectory(prefix="unlockshortcut-version-merge-") as directory:
        paths: list[Path] = [Path(directory) / name for name in ("base", "ours", "theirs")]
        for path, content in zip(paths, contents, strict=True):
            path.write_text(replace_version(content, Version(0, 0, 0)), encoding="utf-8")
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", "merge-file", "-p", str(paths[1]), str(paths[0]), str(paths[2])],
            capture_output=True,
            text=True,
            check=False,
        )
        if not 0 <= result.returncode < 128:
            raise VersioningError(result.stderr.strip() or "Version merge failed")
        if result.returncode:
            conflict: str = result.stdout
            for match in reversed(list(ASSIGNMENT.finditer(conflict))):
                conflict = (
                    conflict[: match.start("version")]
                    + str(max(versions[1:]))
                    + conflict[match.end("version") :]
                )
            ours.write_text(conflict, encoding="utf-8")
        else:
            ours.write_text(replace_version(result.stdout, max(versions[1:])), encoding="utf-8")
        return int(result.returncode != 0)


def install(remote: str, primary: str) -> None:
    """Install repeatable clone-local hooks, refusing to replace existing integrations."""
    root: Path = Path(git("rev-parse", "--show-toplevel"))
    common: Path = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir"))
    managed: Path = common / "versioning-hooks"
    configured: str = setting("core.hooksPath")
    if (
        configured
        and Path(configured).resolve() != managed.resolve()
        and configured != setting("versioning.installedHooksPath")
    ):
        raise VersioningError(
            "Existing core.hooksPath: integrate its hooks explicitly before installing"
        )
    existing: Path = Path(git("rev-parse", "--git-path", "hooks"))
    for directory in {existing, managed}:
        if directory.exists():
            for hook in directory.iterdir():
                if hook.is_file() and not hook.name.endswith(".sample"):
                    if MANAGED not in hook.read_text(encoding="utf-8", errors="replace"):
                        raise VersioningError(
                            f"Existing hook {hook.name}: chain it before installing"
                        )
    interpreter: str = shlex.quote(sys.executable)
    script: str = '"$(git rev-parse --show-toplevel)/scripts/app_versioning.py"'
    driver: str = f"{interpreter} {script} merge-driver '%O' '%A' '%B'"
    old_driver: str = setting("merge.app-version.driver")
    if old_driver and old_driver not in (driver, setting("versioning.installedDriver")):
        raise VersioningError("Existing app-version merge driver: integrate it before installing")
    if not (root / SOURCE).is_file():
        raise VersioningError(f"Missing shared source: {SOURCE}")
    git("remote", "get-url", remote)
    if not succeeds("show-ref", "--verify", f"refs/heads/{primary}") and not succeeds(
        "show-ref", "--verify", f"refs/remotes/{remote}/{primary}"
    ):
        raise VersioningError(f"Cannot find primary branch {primary}; fetch it before installing")
    managed.mkdir(parents=True, exist_ok=True)
    commands: dict[str, str] = {
        "pre-commit": "prepare",
        "pre-merge-commit": "prepare --merge",
        "prepare-commit-msg": 'annotate "$@"',
        "post-commit": "synchronize-index",
    }
    for name, command in commands.items():
        installed_hook: Path = managed / name
        installed_hook.write_text(
            f"#!/bin/sh\n{MANAGED}\nexec {interpreter} {script} {command}\n", encoding="utf-8"
        )
        installed_hook.chmod(0o755)
    for key, value in {
        "core.hooksPath": str(managed),
        "merge.app-version.driver": driver,
        "merge.app-version.name": "Higher compatible application version; retain source edits",
        "versioning.remote": remote,
        "versioning.primary": primary,
        "versioning.installedHooksPath": str(managed),
        "versioning.installedDriver": driver,
    }.items():
        git("config", "--local", key, value)
    print(f"Installed application version hooks for {remote}/{primary} using {sys.executable}")


def main() -> int:
    """Dispatch the installer, classification command, and Git hook entry points."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    commands: argparse._SubParsersAction[argparse.ArgumentParser] = parser.add_subparsers(
        dest="command", required=True
    )
    installer: argparse.ArgumentParser = commands.add_parser("install")
    installer.add_argument("--remote", default="origin")
    installer.add_argument("--primary", default="main")
    classifier: argparse.ArgumentParser = commands.add_parser("classify")
    classifier.add_argument("intent", choices=("feature", "fix"))
    preparer: argparse.ArgumentParser = commands.add_parser("prepare")
    preparer.add_argument("--merge", action="store_true")
    commands.add_parser("synchronize-index")
    annotator: argparse.ArgumentParser = commands.add_parser("annotate")
    annotator.add_argument("path", type=Path)
    annotator.add_argument("source", nargs="?", default="")
    annotator.add_argument("commit", nargs="?")
    merger: argparse.ArgumentParser = commands.add_parser("merge-driver")
    for name in ("base", "ours", "theirs"):
        merger.add_argument(name, type=Path)
    arguments: argparse.Namespace = parser.parse_args()
    try:
        if arguments.command == "install":
            install(arguments.remote, arguments.primary)
        elif arguments.command == "classify":
            classify(arguments.intent)
        elif arguments.command == "prepare":
            prepare(arguments.merge)
        elif arguments.command == "annotate":
            annotate_message(arguments.path, arguments.source)
        elif arguments.command == "synchronize-index":
            synchronize_index()
        elif arguments.command == "merge-driver":
            return merge_driver(arguments.base, arguments.ours, arguments.theirs)
    except (VersioningError, OSError, ValueError) as error:
        print(f"Application versioning: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
