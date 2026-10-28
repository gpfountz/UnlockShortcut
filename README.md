<!-- SPDX-FileCopyrightText: 2026 Greg Pfountz -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# UnlockShortcut

`UnlockShortcut` is a small, typed Python LaunchAgent daemon. It listens for the
macOS screen-unlock notification and invokes an ordered list of Shortcuts after
the first unlock of each local calendar day. Its runtime files are deliberately
kept together in `~/.config/UnlockShortcut`.

## License and legal notices

Copyright © 2026 Greg Pfountz. UnlockShortcut is licensed under
[GPL-3.0-only](LICENSE), with no warranty as described in the full license.
See [copyright and scope](COPYRIGHT.md), [reuse and contributions](CONTRIBUTING.md),
and [third-party notices](src/unlockshortcut/licenses/THIRD_PARTY_NOTICES.md).

After installing this version, read the full notices offline without starting
the daemon or running any Shortcuts:

```zsh
/usr/local/UnlockStorage/.venv/bin/unlockshortcut --license
/usr/local/UnlockStorage/.venv/bin/unlockshortcut --third-party-notices
/usr/local/UnlockStorage/.venv/bin/unlockshortcut --version
```

For a source checkout, use `.venv/bin/python -m unlockshortcut.cli` with
`PYTHONPATH=src` and the same options. Running the installed command with no options
starts the daemon as before.

To verify distributions, use a development environment with the `build` frontend
available, then run:

```zsh
python -m build --outdir /private/tmp/unlockshortcut-dist-check
UNLOCKSHORTCUT_ARTIFACTS=/private/tmp/unlockshortcut-dist-check .venv/bin/python -m pytest
```

The artifact tests inspect both the wheel and source archive and run legal
commands from an extracted wheel without installing it. Without that environment
variable, ordinary tests skip only the optional built-artifact checks.

## Configure the daily Shortcuts

The default configuration runs:

```text
/usr/bin/shortcuts run WANUsage
```

UnlockShortcut saves progress after each successful Shortcut. If a later one
fails, the next unlock resumes there without repeating earlier successes.

## Deploy or update

While logged into your macOS desktop, run this from the checkout as your normal
user (without `sudo`):

```zsh
cd /Users/greg/Library/CloudStorage/SynologyDrive-home/Codex/UnlockShortcut
git pull
./scripts/deploy.sh
```

The script can also be called by its absolute path from another directory.
It uses the checkout's `.venv/bin/python` when available, otherwise `python3`;
Python 3.11 or newer, pip, internet access for downloading dependencies,
and permission to use `sudo` are required. Use `./scripts/deploy.sh --help` for help.

The script automatically detects a new installation or an update from the
existing deployment environment or installed LaunchAgent plist. On each run it:

1. Creates an isolated temporary virtual environment using the installed
   deployment Python, or the wrapper's Python for a first installation. Pip reads
   the build and runtime requirements from `pyproject.toml`, downloads their wheels,
   and installs them into that environment. There is no separate requirements file
   or lockfile. All declared pins and bounds remain unchanged; ranges can resolve
   to newer versions within those bounds. No dependency files are rewritten, and
   the checkout's development `.venv` is preserved. Compatible dependency wheels
   must be available; source-only dependencies cause preflight to stop.
2. Runs `pip check`, the canonical GPL and recorded upstream-notice integrity
   checks, and the source CLI's offline legal commands before building. It then
   builds the application with those prepared requirements, without a separate
   build-isolation download or dependency resolution, and installs the result into
   the temporary environment. It checks dependencies, packaged legal commands,
   and the existing configuration (or the example defaults) again. Any failure
   here stops before `sudo`, daemon unloading, or installed-file changes.
3. Creates private `~/.config/UnlockShortcut/config.toml` defaults only when missing.
   Existing configuration, daily progress in `state.json`, and logs are preserved.
4. Unloads a running job, backs up the old application environment by renaming it,
   and creates `/usr/local/UnlockStorage/.venv` using the same Python as preflight.
   It installs the application and dependencies offline from the prepared wheels,
   using `sudo` only for application installation. It reinstalls the current
   checkout even if its version has not changed. Installation or validation failure
   restores the previous environment and restarts a previously running job; a
   failed first installation removes the incomplete environment. The temporary
   environment backup is removed after installation and validation succeed.
5. Copies the repository's LaunchAgent settings into `~/Library/LaunchAgents`, adapting
   executable and log paths for the current user.
6. Enables and loads the LaunchAgent for the current GUI login session.
   It checks that the new daemon is running before reporting success.

The LaunchAgent runs the installed copy. No application version is changed by
deployment. Preflight failures leave the installed application and daemon untouched.
Final offline installation failures restore the previous application environment;
restoring files or restarting the old job can itself fail, and the script reports
that error. Failures after a successful installation, such as plist replacement or
LaunchAgent startup, do not roll back the new packages. Correct the
reported error, inspect `~/.config/UnlockShortcut/launchd.err.log` and
`~/.config/UnlockShortcut/unlockshortcut.log`, then rerun `./scripts/deploy.sh`.

After editing `~/.config/UnlockShortcut/config.toml`, restart the loaded daemon
as your normal user (without `sudo`):

```zsh
./scripts/restart.sh
```

The restart script can also be called by its absolute path from another directory.
`shortcut_names` defines execution order;
the earlier singular `shortcut_name` key remains supported.

### Load it for the current GUI login session

`deploy.sh` performs this automatically. To load an already installed, unloaded
job manually:

```zsh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.pfountz.unlockshortcut.plist
```

### After editing the plist

Edit `launchd/com.pfountz.unlockshortcut.plist` in the repository, then rerun
`./scripts/deploy.sh`. The script replaces the installed plist and reloads the
job automatically, preserving template settings other than its executable and
stdout/stderr log paths. Direct edits to the installed plist are overwritten by
the next deployment; keep lasting changes in the repository template.

If you edit only the installed plist, replace the loaded job manually with:

```zsh
launchctl bootout gui/$(id -u)/com.pfountz.unlockshortcut
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.pfountz.unlockshortcut.plist
```

## Test it before relying on unlock events

Run this once while logged in:

```zsh
/usr/bin/shortcuts run WANUsage
```

It should show the expected alert. To inspect the daemon afterwards:

```zsh
tail -f ~/.config/UnlockShortcut/unlockshortcut.log
```

`com.apple.screenIsUnlocked` is a macOS implementation notification rather than
a documented public API. It is configurable as `unlock_notification` so the
macOS 27 beta can be adapted if Apple changes it. The daemon records success
only after `/usr/bin/shortcuts` exits successfully; a failure is retried on the
next unlock.
