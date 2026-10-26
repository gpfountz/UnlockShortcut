#!/bin/sh
# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# Launch the typed Python deployment helper from any working directory.
set -eu

SCRIPT_DIRECTORY=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIRECTORY=$(dirname -- "$SCRIPT_DIRECTORY")
if [ -x "$PROJECT_DIRECTORY/.venv/bin/python" ]; then
    PYTHON_EXECUTABLE="$PROJECT_DIRECTORY/.venv/bin/python"
else
    PYTHON_EXECUTABLE=python3
fi

exec "$PYTHON_EXECUTABLE" "$SCRIPT_DIRECTORY/deploy.py" "$@"
