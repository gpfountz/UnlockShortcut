# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.
"""Load offline legal resources from both source checkouts and installed packages."""

from __future__ import annotations

from importlib.resources import files


class LegalResourceError(RuntimeError):
    """A required packaged legal document is missing, empty, or unreadable."""


def read_document(name: str) -> str:
    """Read one required legal resource without depending on the working directory."""
    try:
        text: str = files("unlockshortcut").joinpath("licenses", name).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise LegalResourceError(
            f"Cannot read packaged legal document {name}; reinstall the package"
        ) from error
    if not text.strip():
        raise LegalResourceError(f"Packaged legal document {name} is empty; reinstall the package")
    return text


def project_license() -> str:
    """Return the application notice followed by the complete unmodified GPLv3 text."""
    return (
        "UnlockShortcut — Copyright © 2026 Greg Pfountz\n"
        "License: GPL-3.0-only (GNU General Public License, version 3 only).\n"
        "You may redistribute and modify this program under those terms.\n"
        "This program comes with ABSOLUTELY NO WARRANTY; see the full license below.\n\n"
        + read_document("LICENSE")
    )


def third_party_notices() -> str:
    """Return dependency provenance and the complete separately licensed upstream notice."""
    return (
        read_document("THIRD_PARTY_NOTICES.md")
        + "\n"
        + read_document("third-party/PyObjC-LICENSE.txt")
    )
