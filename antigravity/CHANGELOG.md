## 0.8.1

- Expand the terminal in place and keep an Exit full screen button visible.
- Restore the normal controls and scroll position without reloading the terminal.

## 0.8.0

- Raise file downloads and folder ZIP/copy contents to 500 MiB.
- Stream downloads through the browser without retaining full-file JavaScript
  Blobs; keep bounded server reads and extend the file proxy response timeout.
- Refresh the terminal UI with a larger console, compact status/connections,
  grouped keys and consistent mobile styling.
- Validation limitation: disconnected execution workspace prevented Python tests
  and browser rendering. JavaScript syntax and static consistency were checked.

## 0.7.0

- Redesign Files for mobile with compact cards, breadcrumbs, an upload dialog,
  contextual paste controls and a More menu for secondary actions.
- Add explicit confirmed deletion for files and complete folders in writable areas,
  without following symlinks; report incomplete deletions accurately.
- Remove the Share / Save to Files control and its Web Share implementation.
  Keep standard downloads and folder ZIP downloads.

## 0.6.0

- Download complete folders as ZIP archives, including nested and empty folders.
- Add Copy, Move and Paste for files and folders. Copy between file locations;
  move within Inputs or Outputs while keeping Existing files read-only.
- Publish copies atomically without overwriting existing items; reject traversal,
  links, special files, recursive destinations and oversized folder operations.

## 0.5.0

- Add an admin-ingress GitHub connection form for the official remote GitHub MCP
  server, with fine-grained PAT setup, read-only verification and disconnection.
- Keep credentials in private CLI configuration; preserve unrelated MCP entries,
  require explicit repository-tool authorization and restore only scoped grants.
- Add matching setup and publishing guidance; retain local checks, direct main
  publication and no Actions workflows by default.

## 0.4.1

- Package default publishing guidance: local CLI checks, direct-to-main publication
  for authorized projects, and version/changelog bumps for installable app changes.
- Default GitHub Actions off, with explicit per-project opt-in; preserve existing
  automation until the user directs how it should be handled.
- Preserve remote concurrency checks, branch protection, credential exclusions and
  local HAOS builds. This release does not install or authenticate GitHub MCP.

## 0.4.0

- Add opt-in resume_after_restart to managed start and restart_policy for active jobs.
- Persist authorized interrupted-job intent atomically in broker-only storage;
  retain job IDs, fixed working directory and bounded recovery attempt timestamps.
- Restore only after startup isolation checks; retain per-job network/file protections.
- Clear intent on explicit stop, policy disable, observed completion or failure.
- Suspend after three recovery attempts within ten minutes; no failure retry loop.
- Add exclusive broker locking, record validation and live state-directory denial checks.
- Keep default recovery off; application checkpoints and duplicate-action protection
  remain the script's responsibility. HAOS runtime verification is required.

## 0.3.2

- Propose managed foreground jobs for launch failures caused by detaching or the
  short-command limit; route bounded native-terminal mistakes to the run tool.
- Include matching guidance in MCP initialization, exported workspace instructions,
  timeout results and failed execution results, without automatically replaying work.
- Preserve duplicate checks, authorization, file/network restrictions and job limits.
- Distinguish application/policy failures and uncertain transport outcomes.

## 0.3.1

- Export exact MCP schemas into the root-owned control workspace at image build.
- Include routing and job-ID guidance in MCP initialization and workspace instructions.
- Return actionable, redacted validation errors without sending invalid requests to the worker.
- Add a narrow control-workspace read grant; preserve private-directory/native-shell denies.
- Existing scripts and jobs are not rewritten or restarted by argument recovery.

## 0.3.0

- General managed foreground jobs in the existing worker: MCP start, stop, status
  and bounded logs, alongside the existing 90-second run tool.
- Two managed jobs, duplicate protection, 20 recent in-memory records, 256 KiB log
  tails, group termination and temporary networking cleanup. No automatic replay
  after restart and no extra persistent service.
- Retain AppArmor/seccomp/filesystem/public-only egress restrictions. Managed
  processes use reduced priority and a 24-hour CPU budget; other limits remain.
- Add narrow tool grants and generic guidance for existing/future foreground
  scripts. Preserve user scripts; daemon/PID-file launchers need adaptation.
- Test lifecycle, failures, duplicate/capacity handling, logs and cleanup locally;
  full namespace execution requires verification on HAOS.

## 0.2.6

- Allow anonymous Unix stream socketpairs used by curl's threaded DNS resolver.
  AppArmor limits this to unnamed endpoints; seccomp continues denying ordinary
  Unix socket creation and now explicitly restricts socketpair family/type/protocol.
- Verify thread startup and socketpair communication in the live worker check.
- Preserve private/local network blocking, filesystem isolation and job limits.
  Target-device HTTPS verification is still required.

## 0.2.5

- Configure the temporary job's IPv6 address and default route explicitly after
  slirp is ready, using fd00::100/64 and its documented fd00::2 gateway.
- Avoid depending on asynchronous IPv6 router advertisements before firewall
  probes. Previously the private IPv6 probe could fail with ENETUNREACH before
  producing a packet, leaving its reject counter unchanged.
- Preserve mandatory reject-counter verification for all probes; no skipped IPv6
  checks or acceptance of network-unreachable as evidence of filtering.
- Route setup failure stops the job. No host routes, AppArmor permissions, firewall
  allow rules, persistent services or HAOS protection settings are changed.

## 0.2.4

- Fix destination-filter verification: an immediate EPERM/EACCES is not the only
  possible socket result when a packet is rejected. A timeout is not itself proof
  of either successful filtering or a leak.
- Require an increased kernel reject counter for every fixed TCP/UDP probe,
  separately for IPv4/IPv6. TCP connection success, unreadable counters, or no
  counter increase stop the job. Verification runs before every command, while
  only the trusted launcher owns the namespace.
- Remove the old errno-only probe. Preserve private/local destination restrictions,
  capability removal, AppArmor, seccomp, file boundaries and no-fallback behavior.
- Report a bounded protocol/address-category diagnostic if filtering is still
  unverified, without a traceback or personal destination addresses.

## 0.2.3

- Permit public outbound TCP/UDP in a fresh user/network namespace for each worker
  command. Filter nonpublic IPv4/IPv6 destinations and add-on-connected subnets
  using nftables before starting the command; DNS changes cannot bypass IP rules.
- Add per-job slirp networking and a bounded DNS relay to public DNS (1.1.1.1).
  No standalone/persistent service, inbound ports, host networking or extra host
  capabilities. Map only the TUN device needed by rootless networking.
- Drop all namespace capabilities before command execution; preserve enforced
  AppArmor, seccomp, file isolation, denied native tools and 90-second cleanup.
- Replace the all-sockets-denied checks with IP/socket-family and local-destination
  checks. Fail closed if namespace, relay, firewall or confinement setup fails.
- Local unit/filter/AppArmor compilation checks pass; complete networking requires
  device verification because the development environment cannot create user
  namespaces or expose a TUN device.

## 0.2.2

- Accept empty/whitespace-only global MCP configuration placeholders and UTF-8
  byte-order marks. Keep strict validation for nonempty malformed content.
- Preserve the original MCP configuration bytes in a private, one-time backup
  before installing the managed worker entry; retain existing valid servers.

## 0.2.1

- Move no-new-privileges enforcement to the restricted helper, after the AppArmor
  transition and before any command. The broker remains non-root. All command
  identity, filesystem and syscall checks remain mandatory.
- Report the exact settings preparation stage and safe error code/JSON location
  instead of hiding all causes behind one startup error. No configuration values,
  tokens or credentials are logged.
- Validate MCP and managed-state structures before updating settings.

## 0.2.0

- Replace all three permission profiles with one managed policy; remove their
  implementation, configuration, namespace probes, diagnostic endpoint/UI and tests.
- Add a separate-UID, offline MCP command worker with a restricted AppArmor child
  profile, seccomp filter, bounded jobs and fail-closed runtime checks.
- Deny native shell execution; grant only the worker tool, input reads and output
  edits. Preserve user-authored restrictions and existing data.
- Separate the immutable CLI control workspace from generated outputs; remove
  native-sandbox mount exceptions.
- HAOS transition and CLI MCP discovery require device verification after update.

# Changelog

## 0.1.23 — Sandbox proc mount

- Permit proc only at /dev/shm/setup/root/proc/ with exact rw,nosuid,nodev,noexec flags.
- Verify the call arguments against the official CLI 1.3.1 ARM64 binary.
- Apply existing proc write/sensitive-file denials to both /proc and the staged proc path.
- Retain command approvals and deny all unlisted mount operations. Native startup/isolation is still unverified.

## 0.1.22 — Sanitized sandbox error display

- Show the latest sandbox error through the existing admin-ingress diagnostic UI.
- Read at most the last 64 KiB of the current timestamped CLI log; no arbitrary file selection.
- Return only allowlisted mount operations, known paths and errno text; redact unknown arguments and suppress other free-form errors.
- Add manual Refresh diagnostic without executing commands or rerunning the sandbox.
- Keep private CLI directory denies and all sandbox permissions unchanged.

## 0.1.21 — Sandbox staging-root mount

- Permit tmpfs at exactly /dev/shm/setup/root/ with zero mount flags (rw).
- Match the newly observed denial and independently verified CLI 1.3.1 ARM64 call arguments.
- No descendant wildcard, bind/remount grants, new capabilities or automatic command execution.
- Full sandbox startup and isolation remain unverified; later operations may still fail.

## 0.1.20 — Initial sandbox shared-memory mount

- Add one exact tmpfs mount rule for /dev/shm, with zero mount flags (rw).
- Establish the required flags from the checksum-verified official CLI 1.3.1 ARM64 binary; record inspection evidence.
- Retain command approval during sandbox testing. No new capabilities or host access.
- This addresses the identified startup denial; later native sandbox mounts and isolation remain unverified.

## 0.1.19 — Chat profile

- Add Chat mode with artifact review disabled and existing narrow input/output grants.
- Add persistent, validated trusted_read_domains for optional web-read approvals in Chat.
- Replace the managed web-read Ask wildcard in Chat so chosen domain grants can take effect; retain user-authored Ask/Deny rules.
- Keep shell, sandbox bypass, browser actions and MCP tools under approval; do not enable the failing native sandbox in Chat.
- Default new installations to Chat. Existing selected profiles remain unchanged.
- Preserve AppArmor, HAOS privileges and the separate file-service boundary.

## 0.1.18 — AppArmor stage-one test

- Install an add-on-specific enforced profile with only private/rprivate root mount exceptions.
- Use dynamic AppArmor peer labels compatible with Supervisor profile renaming.
- Refuse CLI startup if the expected enforced profile is absent, including default/unconfined fallback.
- Keep command and artifact review enabled even when sandbox prerequisites pass.
- Show the active AppArmor label in diagnostics; native isolation remains unverified.

## 0.1.17

- Record the namespace probe error, exit status and a small allowlist of kernel flags.
- Show diagnostics in mobile controls and add-on startup logs without exposing credentials or process environments.
- Keep the same bounded probe and conservative review fallback; do not change HAOS privileges.

## 0.1.16

- Add managed balanced/review profiles, bounded namespace preflight and conservative review fallback.
- Persist only input-read and output-write grants; back up original settings and retain stricter restrictions.
- Separate protected Inputs and writable Outputs using different non-root service identities.
- Move file routes completely out of the terminal service; protect the file backend with a private ingress key.
- Preserve existing workspace content and provide a read-only Existing files view.
- Show profile startup status; no claim of native sandbox verification on HAOS.

## 0.1.15

- Replace guided deletion and SQLite listing with native API listing and exact-ID deletion.
- Add private, read-only connection setup through the CLI tool environment.
- Require confirmation, recheck state/revision and verify absence after deletion; no automatic retries.

## 0.1.14

- Fully remove offline deletion, Undo, recovery, history mutation routes, locking and their obsolete tests.
- Keep conversation listing read-only and retain native CLI deletion controls.
- Preserve existing on-disk backups without scanning or changing them.

## 0.1.13

- Retire unreliable offline deletion and reject stale delete requests.
- Add a live native CLI deletion panel from each conversation row, with ID paste, F4, Enter and Esc.
- Keep legacy backups and stop automatic startup reconciliation; no automatic native confirmation.

## 0.1.12

- Add searchable Conversations menu with per-entry Delete confirmation and Undo.
- Remove local history only while CLI is stopped; retain recovery backups and block active/nested sessions.
- Recover interrupted moves before starting CLI; leave workspace and artifact files intact.

## 0.1.11

- Add Paste as the first mobile toolbar button, with a temporary manual-paste dialog when clipboard access is unavailable.
- Insert text without Enter; use bracketed paste or flatten newlines when unsupported.
- Bound paste size, reject terminal control characters and clean up temporary buffers.

## 0.1.10

- Add an iPhone-friendly F4 button for deleting the selected conversation in `/resume`.
- Keep the CLI confirmation step and include picker instructions in the mobile UI.

## 0.1.9

- Add touch-scrollable terminal history with page buttons, refresh and return to live.
- Retain 20,000 tmux lines; default adaptive rendering to inline, preserving explicit choices.
- Include Pandoc, a LaTeX PDF engine and fonts; verify PDF creation during image build.

## 0.1.8

- Add file deletion with a confirmation dialog and CSRF-protected POST.
- Download through a named file/blob with an iOS Share / Save to Files option.
- Include both plain and UTF-8 attachment filenames for browser compatibility.

## 0.1.7

- Add a workspace file manager: browse, create folders, upload, download,
  preview text and copy file paths.
- Confine access to /data/workspace, block symlinks, and prevent overwrite.

## 0.1.6

- Add GCC/G++, Make, CMake, Ninja, pkg-config, GDB, clangd, clang-format,
  clang-tidy and cppcheck for native C/C++ development.
- Run C/C++ compile-and-execute checks during image build.

## 0.1.5

- Remove the paste box and source uploader, including backend handlers.
- Keep the live terminal, navigation toolbar, and Google sign-in helper.
- Retain files uploaded previously.

## 0.1.4

- Add mobile terminal with navigation keys and a normal paste box.
- Add UTF-8 source-file uploads, including .c and .h, into unique workspace folders.
- Protect control/upload requests with a per-process CSRF token; no automatic Enter.

## 0.1.3

- Add an ingress sign-in page with a tappable Google OAuth link read directly
  from the current terminal screen, avoiding mobile screenshot/OCR corruption.

## 0.1.2

- Fix non-root Nginx startup by explicitly placing FastCGI, uWSGI and SCGI
  temporary directories under /tmp alongside the existing HTTP/proxy paths.

## 0.1.1

- Fix installation failure: replace unavailable Debian ttyd package with upstream
  1.7.7 binary selected by architecture and verified with a pinned SHA256 hash.

## 0.1.0

- Initial experimental Antigravity Remote add-on.
