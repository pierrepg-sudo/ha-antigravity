# Antigravity Remote

## Managed jobs (0.3.0)

The existing worker now supports arbitrary foreground scripts through five MCP
operations. No additional persistent service is installed.

| Tool | Arguments | Purpose |
| --- | --- | --- |
| run | command | Synchronous command, maximum 90 seconds |
| start | name, command | Start a managed foreground command; returns job ID |
| status | optional job_id | List jobs or inspect one |
| logs | job_id | Read latest 256 KiB of stdout/stderr |
| stop | job_id | Request termination of that job and its descendants |

Use a stable job name (1-64 letters/digits/dots/dashes/underscores). Repeated starts
with an active name or identical command return the existing job. At most two
managed jobs and one short command are allowed concurrently. Start returns before
network initialization completes; inspect status and logs to confirm application
startup. `running` is process state, not an application health check. Stop returns
`stopping`; check status for `stopped` after a two-second termination grace period.
All descendants and temporary networking are then killed and job storage cleaned.

Jobs and their 20-entry bounded history live in the existing broker's memory. They
survive chat disconnections, but stop on add-on shutdown/restart/update and do not
automatically resume. Logs and IDs are not retained across restarts. The generic
feature supports current and future scripts; it does not automatically rewrite
user scripts. Use foreground entry points, not nohup/setsid/backgrounding or
PID-file wrappers. Scripts redirecting stdout/stderr must be adjusted if MCP logs
are desired. For Python, use `python3 -u`. Do not paste credentials into tool
arguments or logs. Existing scripts and user data are preserved.

All five tools receive narrow persistent CLI grants; native terminal execution
stays denied. The same mandatory AppArmor, capability, filesystem, seccomp and
private-network checks apply. Managed jobs use reduced priority and a 24-hour
cumulative CPU budget per process instead of the short command's 60 seconds.
There is no managed wall-clock deadline. Memory/file/process restrictions remain.
Both job types share outputs and the worker UID's process limit, so this is not
isolation between mutually untrusted jobs or an aggregate resource quota.

Update the add-on and restart the CLI to refresh MCP tools and workspace guidance.
Use a new conversation if an old one keeps trying the denied native terminal.
Local lifecycle and policy tests cover the implementation; complete namespace
execution still requires verification on the target HAOS device.

## Resolver compatibility (0.2.6)

The command profile permits anonymous Unix stream socketpairs for curl's threaded
DNS resolver. Ordinary Unix socket creation remains denied by seccomp, so this
exception does not enable connections to local services. Startup verifies thread
creation and data exchange over an anonymous pair inside the final command profile.
Public/private destination filtering and filesystem boundaries are unchanged.
The curl error alone does not prove its cause; validate HTTPS on the target HAOS
installation after updating.

## IPv6 startup routing correction (0.2.5)

The reported `IPv6 private/tcp (errno 101; reject counter unchanged)` means the
probe could not reach a route and therefore did not verify firewall rejection.
The launcher now explicitly assigns `fd00::100/64` to the job's `tap0` interface
and installs its default IPv6 route via slirp's documented gateway `fd00::2`,
after relay readiness and before firewall verification. The job-local address
uses `nodad`: this is a fresh, single-guest namespace with a fixed unused address,
so verification need not wait for asynchronous address configuration.

These changes are inside the temporary job network only. All private/local deny
rules and mandatory kernel-counter tests remain. An unavailable route is still
an error, never a substitute for verified rejection. Update and restart with
Protection mode on, then check the worker status. Actual public IPv6 connectivity
also requires IPv6 support in the host's internet connection.

The routing change has local regression-test coverage but has not yet been
verified on HAOS; the device's startup check is still required.

## Destination check correction (0.2.4)

Version 0.2.3 incorrectly required private-address probes to fail immediately with
EPERM/EACCES. The reported timeout therefore left the worker unavailable; the
screenshot alone does not establish whether packets passed the firewall.

Version 0.2.4 checks the actual kernel reject counters instead. Before **every
command**, the trusted namespace launcher sends bounded fixed probes for IPv4/
IPv6 loopback, private and IPv4 link-local destinations using TCP and UDP. Each
probe must increment the corresponding firewall reject counter. TCP connection
success always fails. Timeouts, connection refusals and UDP send returns cannot
pass without that counter evidence. Counter-read or verification failures stop
execution before DNS helpers or user commands start. No destination permission
was relaxed. The final confined child still verifies its file, capability and
socket-family restrictions.

Update, restart with Protection mode on, then check the worker status. A failure
now names the fixed address category and protocol plus whether the reject counter
changed. Refresh reads the last startup result; it does not rerun probes.

## Public outbound internet (0.2.3)

Worker commands can use public TCP/UDP destinations on any port, including HTTPS,
WebSockets, package downloads and public APIs. No per-domain worker permission
prompt is added. Native terminal tools remain denied; use `ha-restricted-worker`.
This applies to worker commands, not the CLI's separate built-in web tools.

Each job creates a rootless user/network namespace, installs an nftables firewall,
and uses slirp4netns for outbound traffic. Private, loopback, link-local, CGNAT,
multicast, reserved/documentation ranges, IPv6 translation/tunnel ranges and the
add-on's connected subnets are blocked. IPv6 public unicast is supported when the
host has IPv6 connectivity. The filter checks packet destinations, so direct IPs,
redirects and DNS rebinding do not exempt private addresses. The command cannot
open raw/netlink or named/abstract Unix sockets, change the firewall, join another namespace or start
an inbound TCP listener. No ports are published.

For DNS, configured nonpublic resolver addresses are redirected **inside the job**
to a temporary DNS stub, which forwards only to public resolver **1.1.1.1**. The
original local/Home Assistant resolver is not contacted. Public DNS destinations
remain usable directly. The only local socket exception is this job-private DNS
stub on port 53; it does not expose HAOS or any other add-on. Private/internal
hostnames will not work. The stub, network relay and descendants are killed at job
completion, explicit stop or (for `run`) the 90-second deadline. No separate persistent service is installed.

Protection mode stays on. The update maps `/dev/net/tun` and adds user-space
networking/firewall packages; it does not request host NET_ADMIN/SYS_ADMIN,
Docker/Supervisor access, host networking or new mounts. The setup process has
capabilities only in its own new user/network namespace. Commands see namespace
UID 0 mapped exclusively to host UID 1002, with all capabilities removed and root
capability restoration locked off; this is not HAOS/container root.

After updating and restarting, check **Restricted commands ready**. Startup checks
must verify enforced AppArmor, empty capabilities, seccomp, denied credential/file
access, writable outputs, and blocked local TCP/UDP destinations before any user
command runs. Every job must independently install its firewall. Any failure stops
execution; no unrestricted fallback exists. The status is an isolation check, not
an external connectivity test. Start a new CLI conversation to refresh the MCP tool
description, then test a public HTTPS request using that tool.

The full namespace/TUN/firewall path could not be run in the development
environment, which prohibits creating the required user namespace. It must pass
these checks on HAOS. If unavailable, share the worker status error; do not disable
Protection mode or AppArmor to force it to start.

All public internet access means commands can send readable workspace contents to
public services. Existing CLI credentials remain unavailable, but any API keys you
place in readable inputs/outputs are available to those commands. The firewall
cannot identify a private service deliberately published through a public reverse
proxy or your router's public address. Long-running foreground scripts can use managed jobs. Self-detaching daemons and
interactive sessions remain unsupported.

## MCP configuration correction (0.2.2)

Empty global MCP config files are treated as unused placeholders. UTF-8 byte-order
marks are accepted. The original bytes are saved once as
`~/.gemini/config/mcp_config.before-restricted-worker.json` with private permissions
before adding the worker. Existing valid server definitions are retained.
Nonempty malformed JSON still stops startup with a redacted location; it is not
silently discarded. An error at line 1, column 1 alone does not prove which format
problem the file contains.

## Startup correction (0.2.1)

The trusted broker starts as non-root without prematurely setting
no-new-privileges, which can prevent AppArmor profile transitions. Each command
still must enter the restricted child profile, verify its identity, and enable
no-new-privileges and seccomp before the shell runs. No unconfined command fallback
exists. If the container itself inherits NNP from HAOS, the startup check may still
reject the transition; do not disable HAOS protections to override it.

Settings errors now identify the failing stage (CLI settings, managed state,
backup, global MCP config or trusted domains) and errno/JSON coordinates without
printing values. The generic error in the earlier log did not identify its cause.
Share the new startup error if preparation still fails.

## Restricted commands (0.2.0)

There is one managed permission policy. The Chat, Balanced and Review options,
their branches, namespace probe and old native-sandbox diagnostic UI are removed.
The native sandbox mount exceptions are also removed from AppArmor. No historical
conversation, upload, generated file or settings backup is deleted.

Update the add-on and restart with Protection mode **on**. The old
`permission_profile` configuration option no longer exists; if HA retains an
unknown option in the YAML editor, remove that key and save. The code ignores any
stale value rather than implementing a hidden compatibility profile.

Open Web UI shows the worker's startup check result. **Restricted commands ready**
means its separate user, child AppArmor label, syscall filter, denied file/local-network
access, writable outputs and child execution passed checks on this device. A
failed check blocks all worker commands. There is no automatic unconfined fallback.
The status button reads the startup result; it does not rerun a test.

Start a new conversation after upgrading. In `/mcp`, look for
`ha-restricted-worker` and its `run` tool. Ask it to use that tool to create a small
text file in `/data/workspace/outputs`. The built-in terminal tool is deliberately
blocked. This integration uses Google's documented global MCP config and exact
`mcp(ha-restricted-worker/run)` grant (and matching grants for start/stop/status/logs); the basic worker call has been verified on the user's device. No global Always-proceed setting is used.

### Boundaries

- CLI remains UID 1000; the broker and jobs map to host UID 1002, group 1000. The file
  manager retains UID 1001. The broker accepts only CLI-UID clients over a Unix
  socket, with no published endpoint. Jobs inherit neither that socket nor the
  CLI's environment/credentials.
- Each job transitions into the enforced `command_worker` AppArmor child profile,
  verifies its label, UID mapping and dropped capabilities, sets no-new-privileges, closes other descriptors,
  installs seccomp, then starts a shell. Failure at any stage stops the job.
- Inputs `/data/inputs` are read-only. Outputs `/data/workspace/outputs` and private
  per-job temporary storage are writable. System binaries/libraries/fonts and a
  small set of non-secret configuration files are readable. CLI home, private
  runtime files and arbitrary proc files have no AppArmor grant.
- Public outbound TCP/UDP is permitted through the per-job firewall described
  above; private/local networks and named/abstract Unix services are blocked. Trusted website
  domains do not modify this firewall. Built-in web tools retain their own review
  controls.
- Native shell and unsandboxed commands are denied by CLI policy. Input reads,
  output edits and the five worker tools have persistent grants. User-authored
  ask/deny rules remain and can still cause prompts. Other MCP tools do not receive
  automatic grants.
- The CLI starts in a root-owned control workspace, separate from generated
  outputs, so output files cannot install active workspace hooks or MCP servers.
  Do not add generated/untrusted directories as active CLI workspaces.
- One short command runs at a time, at most 90 seconds and 60 CPU seconds per
  process; two managed jobs may also run, without a wall-clock deadline and with
  a 24-hour CPU budget per process. All have 512 MiB virtual memory per process,
  32 processes shared by the worker UID, 32 MiB per file and 256 KiB captured
  output. Descendants are killed on completion/stop/timeout and temporary storage
  is removed. These are not aggregate RAM or disk quotas. Commands can
  modify/delete outputs, and many small files can still consume storage.

This reduces approvals for local compilation, Python processing and Pandoc PDFs.
Use managed jobs for network-dependent scripts needing more than 90 seconds. Package
installation must target writable outputs or temporary storage. Debugging with
ptrace, inbound servers, self-detaching daemons and interactive sessions remain unsupported.
The HAOS protection boundary remains in place; no host mounts, Docker socket or
extra host capabilities are requested.

### Settings and migration

Only `trusted_read_domains` remains configurable. It lists explicit public DNS
hostnames for built-in web-read permissions, not a firewall rule. An empty list
keeps default web approval behavior. Persistent grants are replaced with the
managed narrow set on startup; unrelated CLI preferences and user ask/deny rules
are retained. A private `settings.before-restricted-worker.json` backup is created
once. Existing unrelated MCP definitions are retained without new grants.

Local checks cover settings migration, MCP message handling, broker time/output
bounds, syscall denials, source compilation and offline AppArmor compilation.
The prior AppArmor transition and basic MCP call were verified on the user's HAOS
installation. The new namespace/TUN/firewall path requires device verification;
local tests do not establish that it works on HAOS.

## Status

Source package only. Shell syntax and package structure checked. The official
Linux AMD64 CLI v1.2.17 was downloaded with checksum verification and its
`--help` successfully confirmed the `--remote-control` option. Docker image build,
HAOS ingress, ARM64 execution, Google authentication/persistence and actual Remote
Control have NOT been validated end to end. No Docker daemon or HAOS target was
available during creation. Do not treat this as a production-ready release.
Google's installer recognizes Linux ARM64 and AMD64; that alone is not a runtime test.
The CLI release is downloaded at image build time and can self-update. This is not
a reproducible pinned CLI distribution. The downloaded binary is not included here.

## Install locally

1. Extract this ZIP. Copy the entire `antigravity` folder to `/addons/antigravity`
   on your HAOS machine using Samba or an SSH/file-transfer app with access to
   the add-ons directory. The required result is `/addons/antigravity/config.yaml`.
   Home Assistant's normal configuration folder is NOT the same directory.
2. Open Settings > Apps (called Add-ons in older versions) > App store.
   Use the store menu to check for updates/reload, then find Antigravity Remote
   under Local apps/add-ons. Install it; the first local image build downloads
   Debian packages and Google's CLI, so it requires internet access.
3. Start it and select Open Web UI. Complete Google's sign-in and workspace prompts
   in the terminal using the same Google account as your paid AI Pro plan.
4. Open https://antigravity.google.com on your iPhone and sign in with that account.
   Choose this instance. Select an available Claude model in Antigravity.
5. After confirming it works, enable Start on boot if desired. The CLI starts in a
   persistent tmux session; closing the setup terminal does not terminate it.

You can alternatively put this package's root contents in a Git repository and add
that repository URL in Home Assistant's app-store repository settings. Repository: https://github.com/pierrepg-sudo/ha-antigravity.

## iPhone app experience

Google documents a Home Screen web app, not a native iOS app in the sources checked.
In Safari visit https://antigravity.google.com, sign in, then Share > Add to Home
Screen. Enable Open as Web App if offered. Launch from that icon for a standalone
window. This still uses web technology. The Claude iOS app cannot consume your
Google AI Pro entitlement or connect to this add-on as its backend.

The setup terminal may also be opened within Home Assistant Companion's ingress UI;
it is NOT Google's graphical chat UI. Do not depend on embedding Google's website
inside an iframe: its authentication and framing policies may prevent it.

## First-login limitation

This container has no graphical browser or desktop keyring. Google's docs describe
manual URL/code authentication over SSH, but the exact behavior inside a web PTY
must be tested. If a sign-in URL is offered, open it on your phone and return the
code to the terminal. If authentication requires a localhost callback or a keyring
that is unavailable here, STOP and report the exact non-secret error. Do not paste
Google passwords or session tokens into add-on options. Authentication support may
require a subsequent revision. We deliberately do not fabricate an SSH session or
copy credentials from another application to force login.

## Operation and persistence

The supported interactive `agy --remote-control` path is used. Google's background
service command expects a system service manager, so this container uses tmux
instead. If you exit the CLI, its remote connection ends; the terminal stays open.
Run `agy --remote-control` there to start it again, or restart the add-on.
A reboot creates a new CLI session; it does not promise automatic conversation
resumption. Saved files/settings under the home directory remain available.

/data/home: persistent CLI binary, configuration and any file-backed authentication.
/data/workspace/outputs: generated files; /data/inputs: protected originals.
/opt/antigravity-workspace: root-owned CLI control workspace.
Keyring-only credentials may not persist; this is part of the pending login test.

Stopping the add-on disconnects Remote Control and terminates its running tasks.
Uninstalling it removes its data. Cold backups include its private data and may
contain credentials; protect backups accordingly.

## Isolation

CLI runs as a non-root user. No host network, Docker socket, Supervisor API, Home
Assistant config mounts, privileged mode or published ports are requested. Keep
Protection mode enabled. The setup terminal is admin-only through HA ingress;
nginx accepts only the documented ingress proxy address and ttyd listens on localhost.
Any HA administrator who opens this terminal can use the signed-in Google session.
Google's Remote Control needs outbound internet; do not add router port forwarding.

## Troubleshooting / acceptance checks

- Build failure: retain the non-secret build error; verify internet and architecture.
- Open Web UI fails: check add-on logs, then ingress WebSocket connectivity.
- `agy` does not start: capture the error from the setup terminal.
- No remote instance: finish authentication, ensure CLI is running, use the same account.
- Restart once and confirm reauthentication behavior and workspace persistence.
- Test on ARM64 HAOS before treating Raspberry Pi support as confirmed.
- Model/limit issues: consult your Antigravity account; the wrapper cannot change quota.

## Sources checked 2026-10-05

https://antigravity.google/cli/install.sh
https://www.antigravity.google/docs/cli/install/
https://www.antigravity.google/docs/remote-control/
https://www.antigravity.google/docs/models/
https://developers.home-assistant.io/docs/apps/presentation/
https://developers.home-assistant.io/docs/apps/configuration/

## Version 0.1.1 installation fix

The ARM64 HAOS build log confirmed Debian Bookworm has no ttyd installation
candidate. ttyd is now downloaded from upstream release 1.7.7 with pinned SHA256
checksums for ARM64 and AMD64. Both downloads were verified; the AMD64 binary
was executed locally. Full HAOS build and authentication remain unverified.

## Version 0.1.2 startup fix

The HAOS log showed Nginx could not create /var/lib/nginx/fastcgi as the
non-root agent user. All five Nginx temporary paths now explicitly use /tmp.
Debian Bookworm's AMD64 Nginx passed config/startup checks and denied a
non-ingress HTTP client. The test required a root-only test override because
the test environment disallows switching UID; that override is NOT shipped.
Non-root HAOS startup still requires confirmation on the target machine.

## Version 0.1.3: iPhone sign-in button

Open Web UI now opens a sign-in helper. If the CLI is showing a Google URL,
tap Sign in with Google. This uses the original terminal text, not OCR.
If no URL is available, choose Open terminal, complete initial prompts, then
return and refresh the helper. Copy Google's authorization code and paste it
into the terminal. Reopening Open Web UI returns to the helper.

The helper is a read-only localhost service behind the same admin-only ingress.
It checks required OAuth fields and the Google host before displaying a link.
It does not store or log authentication URLs or authorization codes.
Restarting the add-on changes the login session: always use its current link.

## Version 0.1.5: navigation toolbar

Open Web UI shows the live terminal with Tab, Shift+Tab, arrows,
Shift+Up/Down, Enter, Esc and Backspace buttons. Type directly in the terminal.
Use Google sign-in at the top to open the login helper.

The separate paste box and source-file uploader have been removed, including
backend upload and text-insertion support. Existing uploaded files are retained.

Controls remain behind authenticated HA ingress with a per-process CSRF token.
Only the fixed navigation-key list is accepted by the control endpoint.

## Version 0.1.6: C/C++ development tools

The image now includes GCC/G++, standard development headers, Make, CMake,
Ninja, pkg-config, GDB, clangd, clang-format, clang-tidy and cppcheck.
Antigravity can invoke these terminal tools on source in /data/workspace.
This installs command-line tools; it does not install a VS Code extension
or automatically connect clangd to the CLI as a language server.

Example prompts: "Compile main.c with gcc -Wall -Wextra -g and explain any
warnings", or "Configure this CMake project with Ninja and run its tests."
Native builds target the add-on host (ARM64 on a Raspberry Pi), not a
microcontroller or Windows. Firmware projects need their own SDK/toolchain.
GDB is installed, but live debugging may be restricted by container security
or the CLI sandbox. No privileged mode or ptrace capability has been added.

The image build runs check-c-tools, which compiles and executes C11 and C++17
samples and checks that the other commands are present. To repeat that check,
ask the agent to run /usr/local/bin/check-c-tools. The larger toolchain makes
the initial install/update download and build longer. Full HAOS build still
requires confirmation on the target device.

## Version 0.1.7: file manager

Open Web UI and tap Files at the top. Browse /data/workspace and subfolders,
create folders, upload from iPhone Files (including .c/.cpp), preview UTF-8
text, download files, and copy a path for an Antigravity prompt. Use Terminal
to return. File uploads live on this separate screen, not in the terminal toolbar.

Uploads are limited to 8 MiB each, downloads to 32 MiB, previews to 256 KiB.
Duplicate filenames are rejected; existing content is never overwritten.
Files are not executed or submitted to Google just by uploading. Text editing is not provided. Existing workspace
files are preserved. Symbolic links and special files cannot be opened.

The file manager is behind the existing admin-only Home Assistant ingress.
Mutations require the page's per-process CSRF token. Files outside the workspace,
including /data/home authentication data, are not exposed by these endpoints.

## Version 0.1.9: delete and mobile downloads

Tap Delete beside a regular file, then confirm in the dialog. Deletion is
permanent; folders and symbolic links cannot be deleted with this action.
The API also requires an explicit confirmation value and the page CSRF token.

Download now fetches the file without navigating the terminal away and opens
a save dialog. On iPhone tap Share / Save to Files, then Save to Files in the
system share sheet. If file sharing is unavailable, use Download file.
Some in-app browsers preview downloaded files even with attachment headers;
use Share > Save to Files from the preview or open Home Assistant in Safari.
The file is kept in browser memory until the dialog closes or the page reloads.

## Scrolling terminal output (0.1.9)

Tap **Scroll history** in the add-on's mobile terminal. Swipe within the output or
use **Page up / Page down**. **Refresh history** updates the snapshot without
jumping to the bottom; **Live terminal** returns to typing. Output is displayed as
plain text, not interpreted as HTML. History requests use the existing ingress
and CSRF protections and are not cached or logged.

The add-on retains up to 20,000 lines in tmux memory, lost on add-on restart.
Startup changes an absent or adaptive `altScreenMode` preference to `never`
(inline mode) so future output can enter scrollback. Other settings and explicit
`always`/`never` choices are preserved. If you previously forced `always`, set
Rendering Mode to inline in `/config` and restart the CLI. Previously discarded
output and full-screen redraws cannot be recovered. This controls the add-on's
terminal, not Google's Remote Control chat page.

## Creating PDFs (0.1.9)

Pandoc, pdfLaTeX and standard LaTeX fonts/packages are installed. Ask the agent:
“Create report.md and convert it with Pandoc to /data/workspace/outputs/report.pdf.”
A shell command (run by the agent, or in a shell) is:

```sh
pandoc /data/workspace/outputs/report.md -o /data/workspace/outputs/report.pdf
```

Open **Files** to download the result. Standard text, tables, code blocks and math
are supported; specialist LaTeX packages and all language fonts are not included.
The image build runs a sample PDF conversion and checks its PDF signature. These
packages increase the download size, disk usage and update/build time on HAOS.

## Delete saved conversations (0.1.10)

In the CLI, type `/resume` and press Enter. Highlight the conversation with ↑/↓,
then tap **Delete conversation (F4)** on the mobile toolbar. Review the CLI's
confirmation and press **Enter** to delete or **Esc** to cancel. Repeat for each
conversation. The button sends only F4; it does not automatically confirm deletion
or access conversation database files. Use it only in the conversation picker.
Custom `item.delete` keybindings can change its behavior.

Google's CLI changelog records F4 replacing Ctrl+Delete in version 1.1.13.
The older `/resume` documentation still mentions Ctrl+Delete. If your installed
CLI shows another shortcut, check its version and keybindings. This feature is
for the add-on terminal; it adds no controls to Google's hosted chat website.
Deleting a conversation is separate from the in-memory terminal scrollback.

References:
- https://www.antigravity.google/docs/cli/commands/resume/
- https://github.com/google-antigravity/antigravity-cli/blob/main/CHANGELOG.md

## Paste from iPhone (0.1.11)

Copy text, focus the CLI prompt, and tap **Paste**, the first toolbar button.
Allow clipboard access if iOS asks. If direct clipboard access is unavailable,
a temporary dialog appears: touch and hold its box, choose Paste, and tap
**Insert in terminal**. The dialog is cleared when closed; no permanent paste box
or file-upload control is added to the toolbar.

The button inserts up to 64 KiB of UTF-8 text without sending Enter. Review it
before tapping Enter. Bracketed paste preserves line breaks when the application
supports it; otherwise line breaks become spaces to prevent accidental submission.
Tabs become four spaces. Terminal control characters are rejected. Pasted text
uses a CSRF-protected request and a temporary tmux buffer, removed after use;
this helper does not write it to disk or log it. The CLI may retain submitted prompts.

## Direct native deletion (0.1.15)

After updating or restarting the CLI, ask Antigravity:
“Run /usr/local/bin/antigravity-connect using your terminal tool.”
Do not run it from a plain shell: it needs the API environment supplied to CLI
tools. The command validates the CLI ancestor, allows only a loopback address,
and verifies GetAllCascadeTrajectories before saving a private mode-0600 connection
file outside the workspace. It never deletes a conversation or prints credentials.

Open **Conversations**, refresh, then **Delete → confirm**. No terminal selection,
F4, exit or restart is needed for deletion. The menu uses the live native listing;
its scope is whatever GetAllCascadeTrajectories returns. Inclusion of all archived
or Google-hosted conversations is not established, and no include_archived flag is
sent. Running and unrecognized states are blocked. Test a disposable conversation
first: listing was verified on the user's CLI; deletion is not yet device-verified.

Requests go only to the pinned local process/port, without HTTP proxies or redirects.
The saved process start time is rechecked on every request; a CLI restart requires
reconnection. Tokens stay on the host and never enter browser responses or logs.
Browser mutations require CSRF and explicit confirmation, with a fresh native
lookup and selection revision check. DeleteCascadeTrajectory receives the exact
cascadeId. A follow-up read must confirm absence before success is reported.
Failures are not retried automatically; refresh after an uncertain outcome.

The previous SQLite listing and guided terminal deletion panel have been fully
removed. No history database writes, file deletion fallback, or add-on Undo exists.
Existing legacy backup files are untouched. Antigravity controls native cleanup of
associated conversation data. This internal API may change across CLI versions.
