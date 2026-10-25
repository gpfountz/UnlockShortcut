<!-- SPDX-FileCopyrightText: 2026 Greg Pfountz -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Security Policy

## System and Scope

UnlockShortcut is maintained by Greg Pfountz. This policy covers the whole
repository: the Python daemon and CLI, packaged resources, LaunchAgent definition,
installation instructions, development scripts, tests, and build configuration.

The documented deployment is a LaunchAgent running as the logged-in macOS user,
using an installed package under `/usr/local/UnlockStorage`. The source checkout
is separate from that installation. The daemon has no direct network listener;
configured Shortcuts may access networks, files, and other services using their
own permissions.

## Threat Model and Trust Boundaries

Protect the user's files and credentials available to Shortcuts, the integrity of
Shortcut selection and execution, daily progress, logs, and installed code.

The user selects and trusts the configured Shortcuts and manages
`~/.config/UnlockShortcut/config.toml`. Installation administrators, the installed
Python environment, macOS, and PyObjC are dependencies of that trust. Treat
configuration write access as authority to select automation; assess how an
attacker could gain that access before claiming unauthorized execution.

Review distributed notifications, TOML configuration, JSON progress, Shortcut
names and subprocess results, filesystem paths and links, and Git inputs to
development scripts at their actual boundaries. A value is attacker-controlled
only when a concrete actor and reachable path to influence it are established.

## Security Invariants

- Shortcut names remain literal arguments to the fixed `/usr/bin/shortcuts`
  executable. Configuration must not introduce shell evaluation, executable
  substitution, or unintended command options.
- Invalid or unreadable configuration must not start Shortcut execution.
- Progress records successful exit status only, stops after failure, and preserves
  earlier successes for retry. Progress is scheduling data, not an authorization
  record or a guarantee that external side effects occur exactly once.
- Runtime configuration, progress, temporary state, and logs must not enable
  another local user to select automation, redirect file writes, or read sensitive
  data across the intended account boundary.
- Logs must not unnecessarily disclose credentials or sensitive Shortcut output.
- Informational CLI options must not start the daemon or execute Shortcuts.
- Build and development tooling must not turn less-trusted repository metadata,
  paths, or remote output into unintended execution or unrelated file changes.

## Reportable Findings and Severity Context

Report reproducible violations with a realistic actor, reachable input, broken
boundary, and concrete impact. Assess execution under the affected user's
permissions and the actual Shortcuts involved; do not assume root execution,
internet reachability, or the contents of private Shortcuts.

Consider unauthorized automation, cross-account file access or modification,
sensitive log disclosure, command or option injection, and consequential resource
exhaustion. Mere influence over data already fully controlled by an authorized
user does not establish additional privilege; identify the capability gained.

## Exclusions and Accepted Risk

There are no blanket exclusions for dependencies or local attacks. The owner
accepts unlock notifications as scheduling hints, not authentication or proof of
screen lock state. Execution without independently verified unlock is accepted
scheduling behavior; assess any additional unauthorized capability or impact.
Other implementation gaps below are assessment context, not suppression authority.
Bugs wholly inside macOS or independently maintained Shortcuts belong to those
components, while unsafe integration by UnlockShortcut remains in scope.

## Known Limitations and Compensating Controls

The README prescribes a private configuration directory (mode 0700) and
configuration file (mode 0600). Directory creation in the daemon does not repair
existing permissions or verify ownership. File operations do not explicitly
reject symbolic links; a temporary state file followed by replacement is not
proof of protection against hostile filesystem entries.

Missing or malformed state can cause retries. A crash between a Shortcut's
success and saving progress can repeat its side effects; multiple daemon
instances have no shared execution lock. Assess resulting security impact
separately from ordinary scheduling reliability.

Shortcut execution has no timeout, captures output in memory, and logs failure
stderr. The main log has no application-level rotation. Evaluate who can influence
output, how much can be produced, and who can read the resulting logs.

The unlock notification is an undocumented macOS implementation detail. The
observer does not authenticate a sender or independently verify screen lock
state, consistent with the owner-approved scheduling model above. Do not infer
that arbitrary notification posting is possible without platform evidence.

The owner confirmed the per-user deployment and user-managed configuration and
Shortcuts described above. Deployed permissions, notification spoofing behavior,
and private Shortcut contents were not verified during policy preparation.
