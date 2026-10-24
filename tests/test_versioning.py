"""Exercise installed hooks using isolated repositories and local bare remotes."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT: Path = Path(__file__).resolve().parents[1]
SOURCE: str = "src/unlockshortcut/_version.py"


@dataclass
class Repository:
    """An isolated checkout with an explicit identity and no inherited Git configuration."""

    root: Path
    remote: Path
    environment: dict[str, str]

    def run(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a command inside the disposable checkout, reporting useful failures."""
        result: subprocess.CompletedProcess[str] = subprocess.run(
            arguments,
            cwd=self.root,
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if check:
            assert result.returncode == 0, result.stdout + result.stderr
        return result

    def git(self, *arguments: str, check: bool = True) -> str:
        """Run Git with the fixture's configuration and return its output."""
        return self.run("git", *arguments, check=check).stdout.strip()

    def tool(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run the exact script installed in this checkout's hooks."""
        return self.run(sys.executable, "scripts/app_versioning.py", *arguments, check=check)

    def commit(self, name: str = "change") -> str:
        """Commit a real staged change through the installed hooks."""
        path: Path = self.root / "changes.txt"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(name + "\n")
        self.git("add", "changes.txt")
        self.git("commit", "-m", name)
        return self.version()

    def version(self, revision: str = "HEAD") -> str:
        """Read the actual committed version without importing application dependencies."""
        text: str = self.git("show", f"{revision}:{SOURCE}")
        return text.split('__version__: str = "')[1].split('"')[0]

    def fork(self, name: str, intent: str = "fix") -> None:
        """Create and explicitly classify a feature or fix branch."""
        self.git("switch", "-c", name)
        self.tool("classify", intent)


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    """Seed a published 1.0.0 project and install the real versioning hooks."""
    root: Path = tmp_path / "checkout with spaces"
    root.mkdir()
    remote: Path = tmp_path / "remote.git"
    environment: dict[str, str] = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="Versioning Test",
        GIT_AUTHOR_EMAIL="versioning@example.invalid",
        GIT_COMMITTER_NAME="Versioning Test",
        GIT_COMMITTER_EMAIL="versioning@example.invalid",
        GIT_TERMINAL_PROMPT="0",
    )
    environment.pop("APP_VERSIONING_ALLOW_MAJOR", None)
    repo: Repository = Repository(root, remote, environment)
    repo.git("init", "--bare", "--initial-branch=main", str(remote))
    repo.git("init", "--initial-branch=main")
    for relative in ("scripts/app_versioning.py", ".gitattributes", "pyproject.toml"):
        target: Path = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / relative, target)
    source: Path = root / SOURCE
    source.parent.mkdir(parents=True)
    source.write_text('"""Shared version."""\n\n__version__: str = "1.0.0"\n', encoding="utf-8")
    repo.git("add", ".")
    repo.git("commit", "-m", "seed")
    repo.git("remote", "add", "origin", str(remote))
    repo.git("push", "-u", "origin", "main")
    repo.tool("install")
    return repo


def test_main_batches_success_and_failed_unrelated_pushes(repository: Repository) -> None:
    """Only successful publication of this branch closes its batch."""
    repo: Repository = repository
    assert repo.commit("one") == "1.0.1"
    assert repo.commit("two") == "1.0.1"
    repo.git("push")
    assert repo.commit("three") == "1.0.2"
    assert repo.commit("four") == "1.0.2"
    reject: Path = repo.remote / "hooks/pre-receive"
    reject.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    reject.chmod(0o755)
    assert repo.run("git", "push", check=False).returncode != 0
    assert repo.commit("failed push") == "1.0.2"
    reject.unlink()
    repo.git("tag", "test-tag")
    repo.git("push", "origin", "--tags")
    repo.git("push", "origin", "HEAD:other")
    assert repo.commit("unrelated pushes") == "1.0.2"
    repo.git("push")
    assert repo.commit("next batch") == "1.0.3"


def test_feature_minor_once_then_patch_batches(repository: Repository) -> None:
    """A feature receives one durable minor and patch-only PR follow-ups."""
    repo: Repository = repository
    assert repo.commit("patch one") == "1.0.1"
    repo.git("push")
    assert repo.commit("patch two") == "1.0.2"
    repo.git("push")
    repo.fork("codex/new-capability", "feature")
    assert repo.version() == "1.0.2"
    assert repo.commit("feature one") == "1.1.0"
    assert "Versioning-Feature:" in repo.git("log", "-1", "--format=%B")
    assert repo.commit("feature two") == "1.1.0"
    repo.git("push", "-u", "origin", "HEAD")
    assert repo.commit("PR fix one") == "1.1.1"
    assert repo.commit("PR fix two") == "1.1.1"
    repo.git("push")
    assert repo.commit("PR fix next batch") == "1.1.2"


@pytest.mark.parametrize("intent", [None, "fix"])
def test_unknown_and_explicit_fix_use_patches(repository: Repository, intent: str | None) -> None:
    """Feature-like branch spelling never overrides explicit or default fix intent."""
    repo: Repository = repository
    repo.git("switch", "-c", "feature/name-does-not-allocate-a-minor")
    if intent:
        repo.tool("classify", intent)
    assert repo.commit() == "1.0.1"
    assert repo.commit("another") == "1.0.1"


def test_retry_aborted_commit_and_removed_payload(repository: Repository) -> None:
    """A failed commit can retry idempotently, or remove its payload without version-only work."""
    repo: Repository = repository
    repo.fork("codex/feature", "feature")
    (repo.root / "changes.txt").write_text("change\n", encoding="utf-8")
    repo.git("add", "changes.txt")
    assert repo.run("git", "-c", "core.editor=false", "commit", check=False).returncode != 0
    assert repo.version("") == "1.1.0"
    assert repo.version() == "1.0.0"
    repo.git("commit", "-m", "retry")
    assert repo.version() == "1.1.0"
    repo.git("push", "-u", "origin", "HEAD")
    (repo.root / "changes.txt").write_text("second\n", encoding="utf-8")
    repo.git("add", "changes.txt")
    assert repo.run("git", "-c", "core.editor=false", "commit", check=False).returncode != 0
    repo.git("restore", "--staged", "changes.txt")
    assert repo.run("git", "commit", "-m", "removed payload", check=False).returncode != 0
    assert repo.version("") == "1.1.0"
    assert repo.version() == "1.1.0"


def test_empty_commits_and_unpublished_amend(repository: Repository) -> None:
    """Empty operations keep versions fixed and amending an open batch does not bump twice."""
    repo: Repository = repository
    assert repo.run("git", "commit", "-m", "nothing", check=False).returncode != 0
    repo.git("commit", "--allow-empty", "-m", "intentional empty")
    assert repo.version() == "1.0.0"
    assert repo.commit() == "1.0.1"
    repo.git("commit", "--amend", "-m", "amended")
    assert repo.version() == "1.0.1"
    (repo.root / "extra.txt").write_text("amended payload\n", encoding="utf-8")
    repo.git("add", "extra.txt")
    repo.git("commit", "--amend", "--no-edit")
    assert repo.version() == "1.0.1"


def test_partial_staging_preserves_unstaged_version_source_content(repository: Repository) -> None:
    """Only the version field and intended source content enter the commit."""
    repo: Repository = repository
    source: Path = repo.root / SOURCE
    source.write_text(source.read_text() + "\n# intended staged comment\n", encoding="utf-8")
    repo.git("add", SOURCE)
    source.write_text(source.read_text() + "# unstaged comment\n", encoding="utf-8")
    assert repo.commit() == "1.0.1"
    committed: str = repo.git("show", f"HEAD:{SOURCE}")
    assert "intended staged comment" in committed
    assert "unstaged comment" not in committed
    assert "unstaged comment" in source.read_text()
    assert '__version__: str = "1.0.1"' in source.read_text()


def test_alternate_index_and_selected_file_commit(repository: Repository, tmp_path: Path) -> None:
    """Alternate indexes and selected-file commits retain unrelated staged changes."""
    repo: Repository = repository
    index: Path = tmp_path / "alternate-index"
    repo.environment["GIT_INDEX_FILE"] = str(index)
    repo.git("read-tree", "HEAD")
    assert repo.commit("alternate") == "1.0.1"
    del repo.environment["GIT_INDEX_FILE"]
    repo.git("read-tree", "HEAD")
    repo.git("push")
    (repo.root / "unrelated.txt").write_text("staged separately\n", encoding="utf-8")
    repo.git("add", "unrelated.txt")
    (repo.root / "changes.txt").write_text("selected content\n", encoding="utf-8")
    repo.git("commit", "-m", "selected file", "--", "changes.txt")
    assert repo.version() == "1.0.2"
    assert repo.git("diff", "--cached", "--name-only") == "unrelated.txt"
    assert repo.run("git", "cat-file", "-e", "HEAD:unrelated.txt", check=False).returncode != 0


def test_unstaged_version_field_is_rejected(repository: Repository) -> None:
    """An unstaged manual version edit is preserved and produces actionable failure."""
    repo: Repository = repository
    source: Path = repo.root / SOURCE
    source.write_text(source.read_text().replace("1.0.0", "1.0.9"), encoding="utf-8")
    (repo.root / "changes.txt").write_text("payload\n", encoding="utf-8")
    repo.git("add", "changes.txt")
    result: subprocess.CompletedProcess[str] = repo.run("git", "commit", "-m", "edit", check=False)
    assert result.returncode != 0
    assert "Unstaged version edit" in result.stderr
    assert "1.0.9" in source.read_text()
    assert repo.version("") == "1.0.0"


@pytest.mark.parametrize("fast_forward", [False, True])
def test_merge_feature_keeps_incoming_version(repository: Repository, fast_forward: bool) -> None:
    """Both automatic merge commits and fast forwards preserve the allocated feature version."""
    repo: Repository = repository
    repo.fork("codex/feature", "feature")
    assert repo.commit() == "1.1.0"
    repo.git("switch", "main")
    repo.git(
        "merge", "--ff-only" if fast_forward else "--no-ff", "codex/feature", "-m", "merge feature"
    )
    assert repo.version() == "1.1.0"
    assert repo.commit("after merge") == "1.1.0"


def test_merge_older_branch_preserves_newer_version_and_source_edits(
    repository: Repository,
) -> None:
    """The real merge driver keeps newer main versions and independent source comments."""
    repo: Repository = repository
    repo.fork("codex/older", "fix")
    source: Path = repo.root / SOURCE
    source.write_text(source.read_text() + "\n# older branch note\n", encoding="utf-8")
    repo.git("add", SOURCE)
    assert repo.commit() == "1.0.1"
    repo.git("switch", "main")
    repo.fork("codex/newer", "feature")
    (repo.root / "newer.txt").write_text("independent change\n", encoding="utf-8")
    repo.git("add", "newer.txt")
    repo.git("commit", "-m", "new feature")
    repo.git("switch", "main")
    repo.git("merge", "--ff-only", "codex/newer")
    repo.git("merge", "--no-ff", "codex/older", "-m", "older fix")
    assert repo.version() == "1.1.0"
    assert "older branch note" in source.read_text()
    assert (repo.root / "newer.txt").exists()


def test_non_version_merge_conflicts_are_retained(repository: Repository) -> None:
    """Conflicting comments remain genuine conflicts instead of disappearing with the version."""
    repo: Repository = repository
    source: Path = repo.root / SOURCE
    repo.fork("codex/one")
    source.write_text(
        source.read_text().replace("Shared version", "First comment"), encoding="utf-8"
    )
    repo.git("add", SOURCE)
    assert repo.commit() == "1.0.1"
    repo.git("switch", "main")
    source.write_text(
        source.read_text().replace("Shared version", "Second comment"), encoding="utf-8"
    )
    repo.git("add", SOURCE)
    assert repo.commit() == "1.0.1"
    result: subprocess.CompletedProcess[str] = repo.run("git", "merge", "codex/one", check=False)
    assert result.returncode != 0
    assert "<<<<<<<" in source.read_text()
    assert SOURCE in repo.git("diff", "--name-only", "--diff-filter=U")


def test_manual_major_requires_one_commit_override(repository: Repository) -> None:
    """A manual major is rejected unless the documented one-commit override is present."""
    repo: Repository = repository
    source: Path = repo.root / SOURCE
    source.write_text(source.read_text().replace("1.0.0", "2.0.0"), encoding="utf-8")
    repo.git("add", SOURCE)
    result: subprocess.CompletedProcess[str] = repo.run("git", "commit", "-m", "major", check=False)
    assert result.returncode != 0
    assert "APP_VERSIONING_ALLOW_MAJOR=1" in result.stderr
    repo.environment["APP_VERSIONING_ALLOW_MAJOR"] = "1"
    repo.git("commit", "-m", "explicitly authorized major")
    del repo.environment["APP_VERSIONING_ALLOW_MAJOR"]
    assert repo.version() == "2.0.0"
    assert repo.commit("normal batching resumes") == "2.0.0"
    repo.git("push")
    assert repo.commit("next normal batch") == "2.0.1"


def test_install_repeated_and_existing_integrations_are_refused(repository: Repository) -> None:
    """Reinstallation is safe and unrelated hooks or merge drivers cannot be overwritten."""
    repo: Repository = repository
    repo.tool("install")
    managed: Path = Path(repo.git("config", "--get", "core.hooksPath"))
    custom: Path = managed / "post-commit"
    custom.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    result: subprocess.CompletedProcess[str] = repo.tool("install", check=False)
    assert result.returncode != 0
    assert "Existing hook post-commit" in result.stderr
    custom.unlink()
    repo.git("config", "merge.app-version.driver", "custom-merge-driver")
    result = repo.tool("install", check=False)
    assert result.returncode != 0
    assert "Existing app-version merge driver" in result.stderr
    repo.git("config", "core.hooksPath", "custom-hooks")
    result = repo.tool("install", check=False)
    assert result.returncode != 0
    assert "Existing core.hooksPath" in result.stderr


def test_new_clone_rename_and_recreated_feature_keep_identity(
    repository: Repository, tmp_path: Path
) -> None:
    """Feature allocation survives renaming, branch recreation, and a fresh clone."""
    repo: Repository = repository
    repo.fork("codex/feature", "feature")
    assert repo.commit() == "1.1.0"
    repo.git("push", "-u", "origin", "HEAD")
    clone_path: Path = tmp_path / "fresh clone"
    repo.git("clone", "--branch", "codex/feature", str(repo.remote), str(clone_path))
    clone: Repository = Repository(clone_path, repo.remote, repo.environment.copy())
    clone.tool("install")
    assert clone.commit("fresh clone PR fix") == "1.1.1"
    repo.git("branch", "-m", "codex/renamed")
    repo.git("branch", "--unset-upstream")
    assert repo.commit("rename") == "1.1.0"
    repo.git("switch", "main")
    repo.git("branch", "-D", "codex/renamed")
    repo.git("switch", "-c", "codex/recreated", "origin/codex/feature")
    repo.git("branch", "--unset-upstream")
    repo.tool("classify", "feature")
    assert repo.commit("recreated") == "1.1.0"


def test_rebase_replay_preserves_allocated_version(repository: Repository) -> None:
    """Replayed feature commits retain the allocated minor instead of bumping per commit."""
    repo: Repository = repository
    repo.fork("codex/feature", "feature")
    assert repo.commit("first") == "1.1.0"
    assert repo.commit("second") == "1.1.0"
    repo.git("switch", "main")
    (repo.root / "main.txt").write_text("advance base\n", encoding="utf-8")
    repo.git("add", "main.txt")
    repo.git("commit", "-m", "advance main")
    repo.git("switch", "codex/feature")
    repo.git("rebase", "main")
    assert repo.version() == "1.1.0"
    assert repo.commit("after replay") == "1.1.0"


def test_worktree_shares_hooks_but_not_branch_state(repository: Repository, tmp_path: Path) -> None:
    """The shared installer resolves scripts and active indexes in a linked worktree."""
    repo: Repository = repository
    worktree_path: Path = tmp_path / "linked tree"
    repo.git("worktree", "add", "-b", "codex/worktree", str(worktree_path))
    worktree: Repository = Repository(worktree_path, repo.remote, repo.environment.copy())
    worktree.tool("install")
    worktree.tool("classify", "feature")
    assert worktree.commit() == "1.1.0"
    assert repo.commit("independent main") == "1.0.1"


def test_remote_failure_mapping_and_divergence_fail_safely(
    repository: Repository, tmp_path: Path
) -> None:
    """Missing access, unexpected mappings, and remote divergence never guess batch closure."""
    repo: Repository = repository
    repo.git("remote", "set-url", "origin", str(tmp_path / "missing.git"))
    (repo.root / "changes.txt").write_text("payload\n", encoding="utf-8")
    repo.git("add", "changes.txt")
    result: subprocess.CompletedProcess[str] = repo.run(
        "git", "commit", "-m", "offline", check=False
    )
    assert result.returncode != 0
    assert "restore remote access" in result.stderr
    assert repo.version("") == "1.0.0"
    repo.git("remote", "set-url", "origin", str(repo.remote))
    repo.git("config", "branch.main.merge", "refs/heads/other")
    result = repo.run("git", "commit", "-m", "mapping", check=False)
    assert result.returncode != 0
    assert "Expected upstream" in result.stderr
    repo.git("config", "branch.main.merge", "refs/heads/main")
    clone_path: Path = tmp_path / "other author"
    repo.git("clone", str(repo.remote), str(clone_path))
    other: Repository = Repository(clone_path, repo.remote, repo.environment.copy())
    other.commit("other author")
    other.git("push")
    result = repo.run("git", "commit", "-m", "stale", check=False)
    assert result.returncode != 0
    assert "ahead or divergent" in result.stderr
    assert repo.version("") == "1.0.0"


def test_missing_remote_branch_starts_patch_batch(repository: Repository) -> None:
    """An existing repository can start automation before its primary branch is published."""
    repo: Repository = repository
    repo.git("push", "origin", "--delete", "main", check=False)
    # Bare Git protects its current branch by default; permit deletion only in this fixture.
    repo.git("--git-dir", str(repo.remote), "config", "receive.denyDeleteCurrent", "ignore")
    repo.git("push", "origin", "--delete", "main")
    assert repo.commit("unpublished initial batch") == "1.0.1"
    assert repo.commit("same initial batch") == "1.0.1"


def test_stale_tracking_ref_does_not_hide_successful_publication(repository: Repository) -> None:
    """Batch closure depends on the actual remote even when local tracking information is stale."""
    repo: Repository = repository
    previous: str = repo.git("rev-parse", "HEAD")
    assert repo.commit() == "1.0.1"
    repo.git("push")
    repo.git("update-ref", "refs/remotes/origin/main", previous)
    assert repo.commit("after published batch") == "1.0.2"


def test_reclassification_before_first_commit_does_not_consume_minor(
    repository: Repository,
) -> None:
    """Changing mistaken feature intent before the first commit produces a normal patch."""
    repo: Repository = repository
    repo.fork("codex/mistaken", "feature")
    repo.tool("classify", "fix")
    assert repo.commit() == "1.0.1"
    repo.git("push", "-u", "origin", "HEAD")
    assert repo.commit("later fix") == "1.0.2"


def test_feature_identity_after_merge_is_recovered_in_new_clone(
    repository: Repository, tmp_path: Path
) -> None:
    """A feature already merged into primary must not receive another minor in a fresh clone."""
    repo: Repository = repository
    repo.fork("codex/feature", "feature")
    assert repo.commit() == "1.1.0"
    repo.git("push", "-u", "origin", "HEAD")
    repo.git("switch", "main")
    repo.git("merge", "--ff-only", "codex/feature")
    repo.git("push")
    clone_path: Path = tmp_path / "clone after merge"
    repo.git("clone", "--branch", "codex/feature", str(repo.remote), str(clone_path))
    clone: Repository = Repository(clone_path, repo.remote, repo.environment.copy())
    clone.tool("install")
    clone.tool("classify", "feature")
    assert clone.commit("existing PR followup") == "1.1.1"


def test_merge_crossing_majors_requires_explicit_decision(repository: Repository) -> None:
    """Automatic merges cannot silently select a different major application version."""
    repo: Repository = repository
    repo.fork("codex/major")
    source: Path = repo.root / SOURCE
    source.write_text(source.read_text().replace("1.0.0", "2.0.0"), encoding="utf-8")
    repo.git("add", SOURCE)
    repo.environment["APP_VERSIONING_ALLOW_MAJOR"] = "1"
    repo.git("commit", "-m", "explicit major")
    del repo.environment["APP_VERSIONING_ALLOW_MAJOR"]
    repo.git("switch", "main")
    result: subprocess.CompletedProcess[str] = repo.run(
        "git", "merge", "--no-ff", "codex/major", "-m", "merge major", check=False
    )
    assert result.returncode != 0
    assert "crosses application majors" in result.stderr
    assert repo.version() == "1.0.0"
    repo.environment["APP_VERSIONING_ALLOW_MAJOR"] = "1"
    repo.git("commit", "-m", "explicitly accepted major merge")
    assert repo.version() == "2.0.0"


def test_merge_without_commit_uses_the_same_policy(repository: Repository) -> None:
    """A merge paused for review keeps the incoming version when committed later."""
    repo: Repository = repository
    repo.fork("codex/feature", "feature")
    assert repo.commit() == "1.1.0"
    repo.git("switch", "main")
    repo.git("merge", "--no-ff", "--no-commit", "codex/feature")
    repo.git("commit", "-m", "reviewed merge")
    assert repo.version() == "1.1.0"


def test_selected_commit_preserves_unrelated_staged_and_unstaged_source_edits(
    repository: Repository,
) -> None:
    """Post-commit index synchronization updates just the version digits in staged source."""
    repo: Repository = repository
    source: Path = repo.root / SOURCE
    source.write_text(source.read_text() + "\n# staged for a later commit\n", encoding="utf-8")
    repo.git("add", SOURCE)
    source.write_text(source.read_text() + "# only in working file\n", encoding="utf-8")
    (repo.root / "selected.txt").write_text("selected\n", encoding="utf-8")
    repo.git("add", "--intent-to-add", "selected.txt")
    repo.git("commit", "-m", "selected", "--", "selected.txt")
    assert repo.version() == "1.0.1"
    assert "staged for a later commit" not in repo.git("show", f"HEAD:{SOURCE}")
    staged: str = repo.git("show", f":{SOURCE}")
    assert '"1.0.1"' in staged
    assert "staged for a later commit" in staged
    assert "only in working file" not in staged
    assert "only in working file" in source.read_text()


def test_reinstall_after_relocation_and_interpreter_change(
    repository: Repository, tmp_path: Path
) -> None:
    """Managed hooks can be relocated and reinstalled with a quoted interpreter path."""
    repo: Repository = repository
    moved: Path = tmp_path / "relocated checkout"
    repo.root.rename(moved)
    repo.root = moved
    interpreter: Path = tmp_path / "python with spaces"
    interpreter.symlink_to(sys.executable)
    repo.run(str(interpreter), "scripts/app_versioning.py", "install")
    assert repo.commit("after reinstall") == "1.0.1"


def test_unrelated_major_merge_conflict_requires_override(repository: Repository) -> None:
    """The merge driver also rejects incompatible majors when both branches changed versions."""
    repo: Repository = repository
    repo.fork("codex/major")
    source: Path = repo.root / SOURCE
    source.write_text(source.read_text().replace("1.0.0", "2.0.0"), encoding="utf-8")
    repo.git("add", SOURCE)
    repo.environment["APP_VERSIONING_ALLOW_MAJOR"] = "1"
    repo.git("commit", "-m", "explicit major")
    del repo.environment["APP_VERSIONING_ALLOW_MAJOR"]
    repo.git("switch", "main")
    (repo.root / "main.txt").write_text("independent change\n", encoding="utf-8")
    repo.git("add", "main.txt")
    repo.git("commit", "-m", "main patch")
    result: subprocess.CompletedProcess[str] = repo.run(
        "git", "merge", "--no-ff", "codex/major", check=False
    )
    assert result.returncode != 0
    assert "crosses majors" in result.stderr
    assert SOURCE in repo.git("diff", "--name-only", "--diff-filter=U")
    assert repo.version() == "1.0.1"


def test_existing_feature_reclassification_never_allocates_a_second_minor(
    repository: Repository,
) -> None:
    """Switching feature/fix intent preserves an already committed feature allocation."""
    repo: Repository = repository
    repo.fork("codex/feature", "feature")
    assert repo.commit("feature") == "1.1.0"
    repo.git("push", "-u", "origin", "HEAD")
    repo.tool("classify", "fix")
    assert repo.commit("fix intent") == "1.1.1"
    repo.git("push")
    repo.tool("classify", "feature")
    assert repo.commit("feature continuation") == "1.1.2"


def test_migrate_static_package_version_without_resetting(repository: Repository) -> None:
    """The first centralized-source commit reads the old static package version correctly."""
    repo: Repository = repository
    source: Path = repo.root / SOURCE
    metadata: Path = repo.root / "pyproject.toml"
    source.unlink()
    metadata.write_text('[project]\nname = "unlockshortcut"\nversion = "1.2.0"\n', encoding="utf-8")
    repo.git("add", SOURCE, "pyproject.toml")
    repo.git("-c", "core.hooksPath=/dev/null", "commit", "-m", "legacy version source")
    repo.git("push")
    source.write_text('__version__: str = "1.2.0"\n', encoding="utf-8")
    shutil.copy2(PROJECT / "pyproject.toml", metadata)
    repo.git("add", SOURCE, "pyproject.toml")
    repo.git("commit", "-m", "centralize version")
    assert repo.version() == "1.2.1"
