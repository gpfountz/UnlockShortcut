# UnlockShortcut

`UnlockShortcut` is a small, typed Python LaunchAgent daemon. It listens for the
macOS screen-unlock notification and invokes an ordered list of Shortcuts after
the first unlock of each local calendar day. Its runtime files are deliberately
kept together in `~/.config/UnlockShortcut`.

## Configure the daily Shortcuts

The default configuration runs:

```text
/usr/bin/shortcuts run WANUsage
/usr/bin/shortcuts run "Fetch Daily Sudoku"
```

`Fetch Daily Sudoku` should contain a **Run Shell Script** action with:

```zsh
/Users/greg/Applications/Sudoku.app/Contents/MacOS/Sudoku --fetch-daily
```

UnlockShortcut saves progress after each successful Shortcut. If a later one
fails, the next unlock resumes there without repeating earlier successes.

## Install

Build a wheel from this checkout, then install that wheel into the dedicated
deployment directory. The LaunchAgent runs the installed copy, not the source
checkout.

```zsh
cd /Users/greg/Library/CloudStorage/SynologyDrive-home/Codex/UnlockShortcut
.venv/bin/python -m pip wheel . -w dist
sudo mkdir -p /usr/local/UnlockStorage
sudo python3 -m venv /usr/local/UnlockStorage/.venv
sudo /usr/local/UnlockStorage/.venv/bin/python -m pip install --upgrade pip
sudo /usr/local/UnlockStorage/.venv/bin/python -m pip install --upgrade \
  dist/unlockshortcut-<version>-py3-none-any.whl
mkdir -p ~/.config/UnlockShortcut
chmod 700 ~/.config/UnlockShortcut
cp config.example.toml ~/.config/UnlockShortcut/config.toml
chmod 600 ~/.config/UnlockShortcut/config.toml
```

Edit the configuration if needed. `shortcut_names` defines the execution order.
The earlier singular `shortcut_name` key remains supported for existing installs.
Runtime progress is stored in `state.json`, and logs are written to
`unlockshortcut.log` in the same directory.

Copy the LaunchAgent into place. It already uses the installed executable at
`/usr/local/UnlockStorage/.venv/bin/unlockshortcut`.

```zsh
cp launchd/com.pfountz.unlockshortcut.plist \
  ~/Library/LaunchAgents/com.pfountz.unlockshortcut.plist
```

Then load it for the current GUI login session:

```zsh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.pfountz.unlockshortcut.plist
```

For later upgrades, build a new wheel and rerun the `pip install --upgrade`
command above with its new versioned filename. The LaunchAgent does not need to
be reloaded because the executable path remains unchanged.

After editing the plist, replace the loaded job with:

```zsh
launchctl bootout gui/$(id -u)/com.pfountz.unlockshortcut
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.pfountz.unlockshortcut.plist
```

## Test it before relying on unlock events

Run this once while logged in:

```zsh
/usr/bin/shortcuts run "Fetch Daily Sudoku"
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
