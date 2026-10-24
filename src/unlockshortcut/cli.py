# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.
"""Run the LaunchAgent normally or display offline legal information without starting it."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .legal import LegalResourceError, project_license, third_party_notices


def main(arguments: Sequence[str] | None = None) -> int:
    """Handle informational options before importing or starting the macOS daemon."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="unlockshortcut",
        description="Run macOS Shortcuts after the first daily screen unlock.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    legal_options: argparse._MutuallyExclusiveGroup = parser.add_mutually_exclusive_group()
    legal_options.add_argument("--license", action="store_true", help="show the full GPLv3 license")
    legal_options.add_argument(
        "--third-party-notices", action="store_true", help="show dependency notices and licenses"
    )
    options: argparse.Namespace = parser.parse_args(arguments)
    try:
        if options.license:
            print(project_license(), end="")
            return 0
        if options.third_party_notices:
            print(third_party_notices(), end="")
            return 0
    except LegalResourceError as error:
        print(f"UnlockShortcut: {error}", file=sys.stderr)
        return 2
    from .daemon import main as run_daemon

    return run_daemon()


if __name__ == "__main__":
    sys.exit(main())
