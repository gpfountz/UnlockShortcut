<!-- SPDX-FileCopyrightText: 2026 Greg Pfountz -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Third-party notices

UnlockShortcut's original code is GPL-3.0-only. Its wheel contains the project
code and legal documents, with no vendored dependency code or native libraries.
The following dependencies are installed separately by pip and retain their
upstream licenses and authorship.

| Dependency | Observed version on 2026-10-26 | Upstream terms | Notice snapshot |
| --- | --- | --- | --- |
| [pyobjc-framework-Cocoa](https://pypi.org/project/pyobjc-framework-Cocoa/12.2.2/) | 12.2.2 | MIT | `third-party/PyObjC-LICENSE.txt` |
| [pyobjc-core](https://pypi.org/project/pyobjc-core/12.2.2/) | 12.2.2 | MIT | `third-party/PyObjC-LICENSE.txt` |

These versions describe the inspected environment, not dependency pins or a
claim that future versions have been reviewed. The package requires
`pyobjc-framework-Cocoa>=12.2.2,<13`; its core dependency may resolve independently.

The shared notice remains an exact byte copy of Cocoa 12.2.2's installed
`pyobjc_framework_cocoa-12.2.2.dist-info/licenses/LICENSE.txt` and its source
archive's root `LICENSE.txt`. The installed core 12.2.2 distribution advertised
MIT but omitted its license file. The matching `pyobjc_core-12.2.2.tar.gz` from
PyPI contains `pyobjc_core-12.2.2/License.txt`; that file was confirmed
byte-identical to the snapshot. Downloaded wheel and source-archive hashes were
verified against PyPI. Their URLs and hashes, the notice hash, and the core
native module hash are recorded in `third-party/provenance.json`.

The upstream notice refers to libffi as a separately licensed product. Inspection
of the CPython 3.14 core wheel's universal2 `_objc` binary for arm64 and x86_64 showed a
dynamic link to macOS `/usr/lib/libffi.dylib`, along with system Foundation,
CoreFoundation, libobjc, and libSystem libraries. No libffi payload is copied into
the UnlockShortcut wheel. This observation does not inventory a future bundled
Python environment or other platform artifacts.

Python and Apple system frameworks, tools, and Shortcuts remain separate runtime
components. This project does not redistribute them. Build and test tools are
not included in this dependency notice inventory.

Before redistributing dependencies or a complete environment, review that exact
payload, include its required notices, and satisfy applicable source/build
requirements. In particular, do not rely on the core package's incomplete
installed notice metadata. This source adoption does not publish or approve a
bundled application release.

The full unmodified upstream MIT notice follows in the CLI output and is also
available offline in `third-party/PyObjC-LICENSE.txt`.
