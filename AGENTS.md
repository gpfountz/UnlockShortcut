# Project guidance

Use Python for new automation. Annotate variables and function signatures, give
functions well-defined docstrings, and keep functions focused with meaningful
names and consistent formatting.

## Application versions

- Read the shared version from `src/unlockshortcut/_version.py`. Package metadata
  and runtime consumers use this source; do not introduce duplicate literals.
- Install commit-time hooks with `.venv/bin/python scripts/app_versioning.py install`.
- Main and fix branches advance patch once per successfully published push batch.
  Further unpublished commits share the batch version.
- Explicitly classify genuine new feature branches with
  `.venv/bin/python scripts/app_versioning.py classify feature` before committing.
  Allocate one minor per feature; subsequent pushed-batch follow-ups use patches.
  Unknown branches are fixes. Explicit `classify fix` overrides feature intent.
- Preserve `Versioning-Feature` trailers. Merges retain the higher compatible
  version; never downgrade the application version.
- Major changes need an explicit user request and the one-commit
  `APP_VERSIONING_ALLOW_MAJOR=1` override. Keep platform build identifiers separate.
- Do not bump versions on saves, builds, tests, or push attempts. Batch closure
  requires actual publication to the designated same-name `origin` branch.
- Hooks are local and bypassable. See README for installation, supported Git
  operations, recovery, and manual-major instructions.
- Run existing daemon tests and disposable-repository versioning tests before
  delivering changes. This guidance does not authorize commits, pushes, deployment,
  history rewriting, or changes to GitHub settings.
