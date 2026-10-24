<!-- SPDX-FileCopyrightText: 2026 Greg Pfountz -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Contributions and reuse

Contributions intended for inclusion in UnlockShortcut must be provided under
GPL-3.0-only. Submit only material you own or have permission to contribute under
those terms. Contributors retain their copyrights; there is no copyright
assignment or separate contributor license agreement. Preserve existing notices
and add accurate attribution for new authors and separately licensed materials.

Private modifications may remain private. Commercial redistribution is allowed.
If you distribute a covered modified version, preserve the required notices,
identify modifications and their dates, and license the covered work under GPLv3.
For object-code distributions, provide recipients the Corresponding Source using
a method permitted by GPLv3 section 6. Private changes need not all be published
to the world. The [full license](LICENSE) controls these obligations, including
the treatment of applicable interactive legal notices.

Use typed Python and focused, documented functions. Follow [AGENTS.md](AGENTS.md)
and run the daemon, legal-resource, and versioning tests. Version changes belong
to commit-time batches; licensing edits do not require a manually allocated major.

Before distributing an artifact, identify its exact source revision and retain
the source, build instructions, installation materials, and dependencies needed
under the applicable licenses. A source archive must include the project scripts,
tests, configuration example, and LaunchAgent definition. For a downloadable
wheel, one available approach is to provide the matching complete source download
alongside it under GPLv3 section 6(d), with clear directions for recipients.
A moving `main` link alone does not identify the exact artifact source.

The local build checks exercise package contents; they do not publish a release
or establish compliance for a future bundled Python environment or macOS app.
If redistributing dependencies, review their exact payloads and retain all
required upstream notices and any applicable source/build materials.
