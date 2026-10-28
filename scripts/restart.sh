#!/bin/sh
# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# Restart the loaded UnlockShortcut daemon for the current GUI login session.
set -eu

exec /bin/launchctl kickstart -k "gui/$(id -u)/com.pfountz.unlockshortcut"
