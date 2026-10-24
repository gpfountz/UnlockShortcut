<!-- SPDX-FileCopyrightText: 2026 Greg Pfountz -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Development versioning

The authoritative application version is `src/unlockshortcut/_version.py`.
Setuptools reads it for wheel metadata, and Python code can import
`unlockshortcut.__version__`. Nonempty commits prepare version changes.
Builds, tests, saves, and pushes do not edit the version.

Install the clone-local Git hooks after cloning (Python 3.11 or later):

```zsh
.venv/bin/python scripts/app_versioning.py install
```

Repeat installation after moving the checkout or changing its Python environment.
The installer quotes interpreter paths, supports linked worktrees, and refuses
existing custom hooks or a conflicting merge driver so they can be integrated
explicitly. Installation does not commit, push, or deploy anything.

On `main`, the first nonempty commit after a successfully published batch advances
the patch once. Further commits retain that version until the branch is pushed
to `origin` under the same name. A failed push, tags-only push, or push of another
branch leaves the batch open. Each commit verifies the actual remote branch and
its ancestry; unavailable remote access, divergence, or custom publication
mappings stop the commit with recovery instructions. An existing repository with
no published primary branch starts a patch batch from its initial version.

Explicitly classify a genuine feature **before its first commit**:

```zsh
git switch -c codex/my-feature
.venv/bin/python scripts/app_versioning.py classify feature
```

Its first nonempty commit allocates one minor and resets the patch. After its
first successful push, follow-up development and PR fixes use patch batches.
Branch names alone never select a feature. Unclassified branches default to fixes;
to override feature intent, run:

```zsh
.venv/bin/python scripts/app_versioning.py classify fix
```

Classification does not change files. Before the first successful commit, a
mistaken classification can be changed without consuming an allocation. If an
aborted attempt has already staged a version, first restore just that assignment
in the working file and index to the value in `HEAD`, preserving other edits.
After a commit, changing classification retains its allocated version and uses
fix batching; it does not rewrite history. Feature identity is recorded in
`Versioning-Feature` and `Versioning-Branch` commit trailers. Retain the
`Versioning-*` trailers when editing messages.
They allow fresh clones, renamed branches (with an updated same-name upstream),
and branches recreated at their previous commits to reuse an allocation.
A rename changes the publication destination: the batch retains its current
version until the new same-name remote branch is pushed. A branch recreated
from unrelated history has no recoverable identity and
defaults to fix; explicitly classifying it as a feature declares new work.

Fast forwards and merge commits retain the higher compatible application version
without allocating another bump. The version merge driver preserves independent
source edits and leaves actual non-version conflicts for normal resolution.
Unpublished amendments keep the open batch version; rebases retain replayed
versions. Reconcile diverged publication history before starting another batch.
Squash merges and published amendments are unsupported and need explicit
version/history reconciliation; use a normal merge or fast forward. Detached-HEAD
development commits require switching to a branch first.

Major versions require an explicit user request. After that approval, edit and
stage only the intended version and accompanying changes, then use a one-commit
override:

```zsh
APP_VERSIONING_ALLOW_MAJOR=1 git commit -m "Release the explicitly requested major version"
```

Cross-major merges also require an explicit decision: resolve and stage the
chosen version, then commit with the same one-commit override. Normal commits
reject staged major changes and version downgrades. Application
versions do not allocate or reset platform build identifiers; this LaunchAgent
currently has no separate platform build identifier or app bundle.

Hooks preserve the active index, selected-file commits, and unrelated unstaged
source content. Conflicting unstaged edits to the version assignment must be
resolved explicitly. No staged changes and allowed empty commits leave the version
alone. Hook failures leave staged work recoverable, and retries do not allocate
the same batch twice.

These hooks cover only clones where they are installed. They can be bypassed,
and do not cover GitHub web edits, other clones, or CI-created commits. The
repository currently has no CI workflow. Run the behavior tests locally with:

```zsh
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy src scripts/app_versioning.py
```
