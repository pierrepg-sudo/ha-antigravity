# Antigravity Remote

## Publishing defaults (0.4.1)

Packaged workspace instructions default to local CLI checks, direct publication
to main for authorized projects, and an app version/changelog bump when needed
to deliver an installable update. GitHub Actions is off by default; a named project
can opt in by explicit user instruction. Existing server-side workflows are not
automatically disabled or deleted, and repository branch rules still apply.

## GitHub connection setup (0.5.0)

Open **Web UI → GitHub**. Create a fine-grained GitHub personal access token,
choose the repository owner and **Only select repositories**, and grant
**Contents: Read and write**. Metadata read access is automatic. Do not grant
Actions or Workflows permissions. Organization-owned repositories may require
approval. Choose an expiry and reconnect with a replacement token before it expires.
Enter the token only in this protected form, authorize repository tools, and select
**Connect and verify**. Restart the add-on and open a fresh CLI conversation.
The connection is named `ha-github` under MCP tools; it is not a marketplace plugin.

The form configures the official remote server at
`https://api.githubcopilot.com/mcp/`. It first verifies the account and MCP tool
availability without modifying repositories. This does not prove write permission
for every selected repository. A GitHub login alone does not grant repository access.
**Test saved connection** repeats the read-only check. Status reports the last saved
verification, not continuous connectivity. Expired/revoked tokens must be replaced.

Only get_me, get_file_contents, get_commit, list_commits, list_branches, push_files
and delete_file are requested via X-MCP-Tools. Their exact ha-github tool grants are
restored at startup only for the managed connection. User ask/deny rules survive.
There are no Actions tools, wildcard tool grants, shell authentication commands,
or credentials passed to worker scripts. Token permissions restrict repository
access; project authorization still governs when changes may be published.

The admin-only HA ingress form uses CSRF protection, no-store responses and a
password field. The token is saved in mode-0600
`/data/home/.gemini/config/mcp_config.json`, beneath the private agent home. The
worker and file server cannot read it; the CLI is denied direct reads of that
configuration directory. Tokens are never returned by the setup API or logged.
The host agent and root can access this configuration; Home Assistant backups may
contain it. Protect backups and rotate the token if they are exposed. Other MCP
entries are preserved, and setup refuses to overwrite an unmanaged ha-github entry.

**Disconnect** removes the saved entry and its managed tool grants. Restart the
add-on to discard cached credentials. Revoke the token in GitHub for immediate
invalidation; local removal does not revoke it or remove older HA backups.
Native browser OAuth is not configured by this form: it uses GitHub's supported
fine-grained PAT authentication for the official remote MCP server.


## Opt-in restart recovery (0.4.0)

`start` accepts `resume_after_restart: true` only when the user authorizes it.
The default is false. For an already active job, call `restart_policy` with its
full `job_id` and the boolean; this changes the policy without restarting it.
A duplicate start returns the existing job and never silently changes its policy.
Status exposes the policy and recovery_count (attempts within the current window).

The existing broker atomically saves command, fixed outputs working directory,
job identity, restart authorization and attempt timestamps under `/data/worker-state`
(mode 0700, broker-owned; record file 0600). No environment snapshot or credential
file is copied. Do not embed secrets in commands; use existing configuration.
CLI/file services cannot access this directory, restricted commands have no
AppArmor grant, and startup checks verify read/write denial. An exclusive broker
lock prevents duplicate broker instances. Invalid records stop startup, without
silently discarding or executing their contents.

After add-on restart or HAOS reboot, recovery runs only after isolation checks
pass. Every recovered job still passes its per-job network checks. A maximum of
three recovery attempts in ten minutes prevents reboot loops; further recovery
is suspended and reported in status/logs and the add-on log. There is no crash
retry loop: observed normal exit, failure or explicit stop clears restart intent.
Disabling the policy also clears it. Explicit stop is persisted before signalling.
Only interrupted authorized jobs restart, retaining their job ID and fresh logs.
CLI-only restart does not restart the broker. Enable the add-on's **Start on boot**
setting if it should start after HAOS reboots; this update does not change that
setting or opt in any existing job.

Recovery starts the command from the beginning. Scripts must durably restore
positions, balances, offsets and other state and avoid duplicate external actions.
A power loss between an external action and its checkpoint cannot provide
exactly-once execution. A storage-write failure is reported; restart intent may
be stale, so resolve the storage error before rebooting. Backups also contain
restart intent; inspect it before starting a restored installation.

Update, restart with Protection mode ON, and open a fresh conversation. Existing
v0.3.x jobs cannot survive this first update because they have no restart records.
Ask the CLI to inspect a script for safe recovery, then explicitly authorize its
restart policy. Test with a harmless opted-in foreground job before relying on
HAOS reboot recovery; device verification remains required.

## Launch recovery (0.3.2)

Persistent workspace and MCP instructions now require a managed-job proposal when
a launch fails because of native-tool selection, detaching or the short-command
limit. Bounded work still uses run. Timeout and execution-failure responses include
matching diagnosis, duplicate checks, foreground adaptation and authorization
guidance. They never start or replay commands themselves. Worker errors remain
errors; dependency, credential, application and policy failures need separate fixes.
Transport errors report an unknown outcome rather than claiming nothing ran.

Update and restart, then open a fresh conversation. Restart stops existing jobs.
These instructions guide the model; they cannot guarantee every model response.

## Worker discovery (0.3.1)

At image build, the MCP server exports its exact tool schemas to the root-owned
control workspace as WORKER_TOOLS.json and appends them to AGENTS.md. These files
contain no credentials or runtime cache data. Initialization also supplies routing
instructions. Invalid tool arguments return the expected schema before contacting
the broker. Use `status` with `{}` and then `logs` with `job_id` set to the full
returned `id`; never restart a job to recover its ID. Private CLI files stay denied.

Update and restart, then start a new conversation to refresh instructions. This
reduces tool-selection mistakes but cannot guarantee model compliance. Foreground
script adaptation still needs inspection of the actual script; user files are not
silently rewritten. Preserve .env loading and dependency paths without printing
secrets, and keep stdout/stderr attached for the managed logs tool.

## Managed jobs (0.3.0)

The existing worker now supports arbitrary foreground scripts through six MCP
operations. No additional persistent service is installed.

| Tool | Arguments | Purpose |
| --- | --- | --- |
| run | command | Synchronous command, maximum 90 seconds |
| start | name, command, optional resume_after_restart | Start a managed foreground command; returns job ID |
| restart_policy | job_id, resume_after_restart | Enable/disable recovery without restarting an active job |
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
survive chat disconnections and CLI-only restarts. Add-on shutdown/restart/update
stops jobs; only explicitly opted-in interrupted jobs recover. Their IDs are
retained; logs and other history are not retained across restarts. The generic
feature supports current and future scripts; it does not automatically rewrite
user scripts. Use foreground entry points, not nohup/setsid/backgrounding or
PID-file wrappers. Scripts redirecting stdout/stderr must be adjusted if MCP logs
are desired. For Python, use `python3 -u`. Do not paste credentials into tool
arguments or logs. Existing scripts and user data are preserved.

All six tools receive narrow persistent CLI grants; native terminal execution
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
  output edits and the six worker tools have persistent grants. User-authored
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

Uploads are limited to 500 MiB each, downloads to 500 MiB, previews to 256 KiB.
Home Assistant ingress request streaming is enabled so Supervisor forwards large
uploads to the app without its default buffered request size limit. If an older
installation returns HTTP 413 for a file below 500 MiB, update to 0.10.8 or later
and reopen the Web UI. Version 0.10.9 also handles chunked request bodies forwarded
by streaming ingress, enforcing the size limit as bytes arrive and publishing only
after the complete request is validated. Additional external proxies may impose
their own limits.
Duplicate filenames are rejected; existing content is never overwritten.
Files are not executed or submitted to Google just by uploading. Text editing is not provided. Existing workspace
files are preserved. Symbolic links and special files cannot be opened.

The file manager is behind the existing admin-only Home Assistant ingress.
Mutations require the page's per-process CSRF token. Files outside the workspace,
including /data/home authentication data, are not exposed by these endpoints.

## Delete and download files

Tap **Delete** on a file or folder card, then confirm in the dialog. Folder deletion
permanently removes all nested contents; the confirmation names the selected item.
Only Inputs and Outputs permit deletion. Existing files remain read-only, and the
workspace roots themselves cannot be deleted. The API requires explicit confirmation,
a folder-specific kind value for recursive deletion, and the page CSRF token.
Symbolic links at the selected path are blocked. Nested links are removed as links;
their targets are never followed. Stop active writers before deleting their folders.
A permissions error or active writer may cause a partial deletion; the UI reports
this honestly and asks you to refresh before retrying.

**Download** starts a standard browser download. **ZIP** first prepares the folder
and then shows a **Download ZIP** link with its compressed size.
Downloads stream in bounded chunks rather than holding the entire file in the
file service or the page's JavaScript memory. ZIPs are prepared in a temporary
spooled file before transfer; allow time and free disk space for large folders.
Some in-app browsers preview files or open another tab. Open Home Assistant in
Safari if the app does not handle a download correctly. ZIP preparation errors
appear in Files without starting a download. The page cannot confirm that the
browser finished saving the file. No share-sheet or extra save dialog is used.


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

## Saved conversations

Open **Conversations** from the terminal header to manage saved conversations.
Its listing and confirmed deletion tools remain available. The terminal's separate
F4 deletion shortcut button and deletion help panel were removed in 0.8.2.
Deleting a conversation is separate from the in-memory terminal scrollback.

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

## Conversation and project management (0.10.1)

**Open Web UI** now opens Conversations; **Terminal** still opens the console.
Conversations, Files and Terminal link directly to one another. Their controls,
along with the connection pages, share the same primary/secondary button theme
from `ui.css`. Destructive actions retain a distinct red style.
Projects remain collapsed by default. Create a project with **New project**, or
expand one to rename, archive, restore or delete it. Conversations have their own
rename/archive/restore/delete controls. Archiving a project groups its conversations
under Archived without altering each conversation's individual archive flag.
The built-in CLI Project and unclassified groups cannot be deleted/renamed as
projects, but their conversations can be managed individually.

Every project mutation prepares the selection before confirmation and rechecks
it afterwards. Project deletion is limited to 200 conversations per operation,
rejects busy/unknown states and changed selections, and reports partial completion
if a later native request fails. It never retries deletion automatically. Project
deletion asks whether to **Keep folder and files** (the default) or permanently
delete the bound output folder and everything inside it. The final confirmation
shows the freshly checked folder path; a changed folder invalidates confirmation.
Stop workers writing to that folder first. File cleanup runs only after project
deletion is verified. If cleanup fails, check Outputs: some files may have been
removed. Retained folders become ordinary folders in Outputs, even if the deleted
project was archived. No unrelated or unbound folders are deleted.

Files opens in **Outputs**. **Archived projects** is a separate view of archived
projects' generated folders and contents. Archive/Restore in either Conversations
or a project folder's **More** menu in Files updates the same project metadata;
refreshing the other tool shows the change. This is a virtual archive: physical
paths stay unchanged, so existing scripts and worker paths do not break. Download
an archived project ZIP from its folder, not the archive section root. An Outputs
root ZIP still contains all physical output files, including archived projects.

Files blocks direct deletion or moving of any folder still linked to a project,
including archived projects. This protection is checked server-side immediately
before the operation and fails closed if project metadata is unavailable. Use
Conversations to delete the project and choose its file-retention policy. Regular
file and subfolder operations inside a project remain available. Project-aware
renaming uses the existing management confirmation instead of direct file rename.

New projects created here get `/data/workspace/outputs/<project name>`; existing
projects get a folder when opened or used for a new conversation here. Names must
be valid single folder names. Existing unrelated folders are never adopted or
merged automatically: use a unique project name if there is a collision. Existing
files in the outputs root are not moved. Unclassified conversations use the root.
The launcher supplies a session-specific output directory to the restricted MCP
worker. Commands default to it, and MCP instructions tell the agent to use it for
generated files. Explicit paths in existing scripts still take precedence. The
protected CLI control workspace remains unchanged; writable outputs are not loaded
as trusted workspace hooks or configuration. Use Conversations to switch project
contexts; switching in the CLI's own picker does not reinitialize MCP defaults.

Files has **More → Rename** for regular files/folders, with atomic no-overwrite
renames. Renaming a managed root output folder through Files updates the project
name and binding too. Renaming from Conversations renames the bound output folder.
Stop workers using that folder first, then reopen its conversations afterwards to
refresh their session defaults. Project metadata and filesystem updates are not a
single native transaction; if the API fails, the folder binding remains accurate
and the UI reports failure. Refresh before retrying.

Terminal has a **Saved model for this conversation** dropdown. Its options come
from the signed-in CLI's `agy models` catalog, not a hard-coded list.
The catalog reader accepts name-first and slug-first reports, tab/table formatting
and output on either stream. Failed or timed-out requests show **Models unavailable**
with **Refresh models** for retry; `/model` remains available in the terminal.
Choosing a model requires confirmation, checks that the same conversation is still active and idle,
then restarts that terminal with `--model=<slug>`. Preferences are stored by
conversation ID and reapplied on opening and add-on restart. Clear the override to
use the CLI default. This selector manages its own explicit preferences.
An unavailable saved model can be cleared with **More → Reset model preference**
on its conversation before reopening it.
Changes made through the CLI's `/model` command are not imported into it. Send a first
message or open a saved conversation if the session cache has no active ID yet.
Available-model/account behavior and the complete signed-in HAOS handoff require
device validation; local tests use an unsigned-in CLI with outbound networking denied.

Startup persists the previously synthetic `outside-of-project` record so the CLI
can resolve unclassified conversations on resume. Existing project records are
preserved. The invalid generated `unsandboxed(*)` deny entry is removed; `command(*)`
remains denied, with the existing worker isolation and private-path protections.

### Native connection and deletion

The Conversations page is also a session launcher. Choose **New conversation**,
select an existing project or leave **No project**, then confirm. Existing entries
have **Open in terminal**. Both actions hand off to the terminal controls page.
Save unsent terminal text first: switching gracefully stops the idle CLI process
and launches its replacement with `--conversation=<exact ID>`. Running or unknown
native trajectory states block switching. Managed workers are separate processes.
The launcher accepts only validated requests through a private mode-0600 Unix
socket, rechecks the child PID/start time and live idle states, and never sends
blind terminal keystrokes or force-kills the CLI. Session changes require browser
CSRF and confirmation. A lost response is not automatically retried.

New conversations use native `StartCascade` with an explicit project environment.
**No project** uses the CLI's `outside-of-project` identifier, not its default
`CLI Project`. The returned ID and project metadata are verified before handing
off. If creation succeeds but handoff fails, refresh history before trying again;
the created conversation is preserved. Session switching reconnects the local API
and remote-control session. The real-CLI tests cover creation and project metadata;
the complete signed-in terminal handoff still requires HAOS device validation.

The add-on now owns local API connection setup as part of CLI startup. No hooks,
terminal messages or manual pairing are required. The launcher generates a fresh
random token and supplies it through the CLI's `--csrf_token` option. It reads the
HTTP port from a private log created for that child, verifies read-only native
listing, then atomically stores the connection mode 0600 outside the workspace.
Only loopback addresses are tried. The saved process owner, PID and start time
are checked on every request; process-executable inspection is not required because
the launcher owns the child and supplies its authentication token.

The CLI's local server rejects incorrect tokens. The token is present in the CLI
process arguments: native file-tool access to /proc is denied and the restricted
worker's AppArmor profile does not allow access to process command lines. Tokens
never enter browser responses, worker commands or add-on logs. Temporary CLI logs
remain in a private directory for the session and are removed on normal exit.
The connection file is removed on CLI exit and replaced on startup.

Startup retries read-only verification for up to 60 seconds and reports failure
without saving an unverified connection. The CLI remains usable if pairing fails.
This interface and startup log format are upstream implementation details, tested
against Google's real Linux CLI 1.3.4 without login. The integration runner adapts
process identity lookup when its /proc mount uses host PIDs; HTTP/token checks and
private persistence use the real CLI. Production rejects a mismatched /proc namespace.
A populated signed-in history
and the user's HAOS environment still need device validation. Older/future CLI
versions may differ. The obsolete ha-conversations hook is removed on upgrade;
other global hooks are preserved. The antigravity-connect helper is removed.

The page refreshes every 15 seconds while visible, immediately on return, and backs
off to 30–60 seconds after errors. Refresh requests do not overlap. Hidden pages and
open conversation dialogs pause polling. Failed reads clear the list so stale entries
cannot be deleted. Search text is retained. Manual Refresh remains available.

Open **Conversations**, then **Delete → confirm**. Listing reads
`/data/home/.gemini/antigravity-cli/conversation_summaries.db` in SQLite read-only
mode and matches rows against `.db`/`.pb` files in its `conversations` directory.
This includes saved conversations not loaded into the current language-server
memory. Stale index rows without backing files are excluded, as are empty unsaved
API placeholders. Child conversations are managed with their parent. Google-hosted
history and the picker's Other tab are outside this local CLI view.

Titles, steps and dates come from the saved index. Missing or unsupported metadata
never grants deletion: such entries are blocked or an explicit read error is shown.
The index's busy flag and the API's live busy state both prevent deletion. No
conversation is loaded merely by opening or refreshing this page.

Requests go only to the pinned local process/port, without HTTP proxies or redirects.
The saved process start time is rechecked on every request; an add-on restart
establishes a fresh connection automatically. Tokens stay on the host and never enter
browser responses or logs. Browser mutations require CSRF and explicit confirmation.
For a saved entry, LoadTrajectory loads the selected ID before checking its native
idle state. The saved index and backing-file revision are checked again before
DeleteCascadeTrajectory receives the exact ID. If loading changes/migrates the
conversation, preparation refreshes the selection automatically. Changes after the
confirmation appears require reviewing and confirming the refreshed selection again.

Success requires absence from both the native listing and backing files. Deletions
are never retried automatically. The add-on never edits the history database,
deletes history files itself, or drives terminal keys. Existing legacy backups are
untouched. Antigravity controls cleanup of associated data; there is no add-on Undo.

Tests cover 22 saved entries while the API contains only an empty placeholder,
read-only listing, busy/unknown states, stale confirmations, unsupported schemas,
symlink rejection, and failed or incomplete deletion. An isolated real CLI 1.3.4
test creates two conversation databases, restarts, deletes one through the production
handler, restarts again, and verifies the other remains loadable. Summary-index
metadata is seeded for those empty synthetic conversations; no Google login is used.
The test CLI and descendants have outgoing connect/datagram syscalls denied. Live
signed-in HAOS deletion still needs device validation. The internal API and index
schema may change between upstream releases.


## Folder downloads, copy and move (0.6.0)

In **Files**, choose **Download ZIP** beside a folder, or **Download folder ZIP**
to download the folder currently open. All nested files and folders, including hidden files, hidden folders and empty
folders, are included. When preparation succeeds, Files shows the compressed size and a **Download ZIP**
link. Tap that link within five minutes; it works once. Preparation failures appear
on the page and do not start a download. At most three prepared archives are held;
unused archives are removed automatically after five minutes. ZIP generation is limited to
500 MiB of uncompressed file contents, 10,000 entries and 64 levels. A link, special
file, unreadable item or detected source change aborts the archive with an error;
contents are never silently skipped. This is not a snapshot of actively edited data.
Pause writers when you need a consistent archive or copy.

Choose **Copy** or **Move** beside a file/folder, browse to its destination, then
select **Paste** and accept or change the name. **Cancel copy/move** clears the
selection. The selection remains only in this browser page and is lost on reload.
Copy supports Inputs, Outputs and the read-only Existing files as sources; destinations
must be Inputs or Outputs. Move is limited to the same writable location to preserve
ownership and permission boundaries. To transfer between locations, use Copy; it
leaves the source intact. Copy uses the destination area's normal permissions and retains owner/group executable bits.

Existing names are never replaced. Copies are built in a private temporary folder
and published atomically; failed copies clean up temporary data and preserve the
source. Copy shares the ZIP size/entry/depth limits. Moving uses an atomic no-replace
rename and does not read the contents. A folder cannot be pasted into itself or a
descendant. The existing ingress authentication, CSRF checks, root restrictions and
separate file-service identity apply to all new operations. No new agent permission
or network access is granted. Device-level HAOS verification is still required.


## Updated Files interface (0.7.0)

Files uses responsive cards, folder breadcrumbs and compact toolbars. Download and
Delete stay visible on every writable file/folder card. **More** contains Copy,
Move and File path. The paste bar appears after selecting Copy or Move. Upload opens
a dedicated dialog, while detailed limits are under **File limits & permissions**.
Folder deletion requires confirmation and never follows links outside the selected
folder. No change grants the agent additional access to Inputs or credentials.

## Larger downloads and terminal layout (0.8.0)

File downloads and file/folder copies support 500 MiB (524,288,000 bytes).
Folder ZIPs have the same limit on total uncompressed file contents; the existing
10,000-entry and 64-level limits remain. Uploads allow 500 MiB and text previews
256 KiB. Pause active writers when a consistent copy or archive matters.
The worker's separate resource limits have not changed.

The terminal page now uses the same visual style as Files, with a larger console,
compact Worker status and Connections panels, and grouped mobile keys. Files and
Conversations remain in the header; Google sign-in and GitHub are in Connections.
More keys contains Shift+Tab, selection arrows and Backspace. History, paste fallback and full-screen access remain available.

For this release the execution workspace was unavailable. JavaScript syntax and
static consistency checks were performed; Python tests and browser/HAOS rendering
could not be run. Added streaming boundary tests await execution.


## Leaving full-screen terminal (0.8.1)

The **Full-screen terminal** button expands the current terminal inside the Web UI.
An **Exit full screen** button stays visible above it and returns to the normal
controls and page position. The iframe stays loaded, so this does not reconnect or
restart the CLI. The Home Assistant app's own header may remain visible.
If you still have the previous standalone terminal open, reopen the add-on's Web UI
after updating to use the new expand/exit controls.

Deletion automatically prepares the selected saved conversation before opening an actionable confirmation and again before sending delete. Preparation can load/migrate old history but never deletes. A changed revision requires another explicit confirmation. Failed or ambiguous delete requests are never retried automatically.


Conversation groups use the saved index project_id and read-only local
~/.gemini/config/projects/*.json names. Unknown names display their project ID; entries without
a project appear under No project. Archived conversations have their own section
and project groups. Search includes project names. Archive state is read from
raw_summary protobuf annotations (CLI 1.3.4 schema), with live API annotations
taking precedence. Missing or malformed archive metadata is labelled, never
inferred from inactivity. Grouping does not archive, move or modify history.

Project folders start collapsed. Tap a project heading to expand or collapse its conversations. Folder choices are
retained while the page is open, including automatic refreshes. Search temporarily
expands matching folders; clearing search restores your choices.


The launcher uses `--remote-control --continue`. The CLI reopens the most recent
conversation for the startup workspace using its own session cache. If that
workspace has no saved session, or it was deleted, the CLI starts a fresh session.
This avoids accumulating empty startup conversations during normal restarts;
existing conversations are not automatically deleted. This reopens context without
submitting a new prompt. Use /new when you want a fresh conversation.
See https://antigravity.google/docs/cli/commands/resume for the native cache behavior.

## Upload a folder (0.10.4)

In Files, open the destination, select **Upload**, then choose **Folder** from
Upload type. Choose the local folder and press **Upload**. Its name becomes a new
folder in the current location; nested paths and any hidden files supplied by the
browser are preserved. An existing destination name stops the upload instead of
merging or overwriting. Inputs retain their existing agent read-only permissions.

The selection is checked before uploading: 500 MiB per file, 500 MiB total,
10,000 file/folder entries and 64 levels. Files upload one at a time with progress.
Keep the page open until completion. Interrupted uploads retain their partial
folder; inspect and rename or remove it before retrying. Nothing is automatically
deleted after a failed transfer.

Folder selection depends on the browser. Empty directories and files omitted by
the picker cannot be uploaded. If folder selection is unavailable on your phone,
use a desktop browser. Uploading a ZIP as a file does not extract it.

## Shared navigation and large uploads (0.10.6)

Files, Conversations and Terminal keep their navigation links at the upper right;
on narrow screens the links stack vertically. Files and Conversations use the
same collapsed **More** disclosure. Project Rename, Archive/Restore and Delete
are inside the project's **More** menu.

The Files uploader sends the file body directly to the file service, which writes
in 64 KiB chunks and publishes the destination only after the complete upload.
The browser does not base64-encode the file. The app proxy accepts up to 500 MiB
per file and streams the request. An interrupted individual file upload removes
its temporary file; earlier completed files in a folder upload remain intact.

## Upload feedback and shared workspace styling (0.10.7)

Uploads show a progress bar, transferred/total bytes and average transfer speed.
Folder uploads report progress across the selected files. After all bytes are
sent, the screen says **Finalizing** until the server confirms that the file was
saved. Bytes sent do not by themselves confirm a saved file. Keep the page open.

**Cancel upload** stops the active transfer and any remaining folder uploads.
Previously completed files stay in place. Check the destination before retrying
when cancellation happens during finalization or the connection is lost.
The page reports no recent progress after 15 seconds, aborts a transfer after
two minutes without progress, and allows three minutes for server confirmation.
Proxy errors include the HTTP status when no JSON error is available.

Files, Conversations and Terminal share panel borders, spacing, typography,
button roles, dialog styling and More disclosures. Navigation remains at the
upper right; Files toolbar controls use two columns on small screens.

### Extract a ZIP in Files

Choose **More → Extract ZIP** on a ZIP file in a writable location. Contents are extracted directly beside the ZIP without an extra archive-name folder. Folders already inside the archive are preserved, including hidden files and empty directories. The original ZIP is retained. Existing destination files or folders are never overwritten or merged; if a name conflicts, move the ZIP to an empty folder first. Extraction permits up to 500 MiB of expanded contents, 10,000 entries (including parent folders), and 64 levels. Unsafe paths, symbolic links, special files and encrypted or damaged archives are rejected before publishing any contents. A filesystem error during final publication may leave some extracted items; the error asks you to check the destination before retrying.

### Projects created in the official remote

The native CLI currently returns `~/Documents` as its default project directory when present, otherwise its home directory; it has no configurable project-root field. At startup the add-on creates `/data/home/Documents` as a compatibility link to `/data/workspace/outputs`. A remote project created under that default is physically stored in Outputs. The official remote may display the Documents alias rather than the canonical Outputs path. You can also explicitly select `/data/workspace/outputs/<project name>`. Existing Documents folders or different links are preserved, with a startup notice; they are never replaced automatically. Existing projects elsewhere under `/data/home` are not relocated.

Files and Conversations automatically register projects whose native metadata references exactly one real immediate Output folder, including the managed Documents alias. They receive project archive/restore, rename and deletion protection on refresh. Names alone never establish a link: unrelated folders, symlinks, nested paths and folders claimed by multiple projects are not automatically adopted. Renaming a linked project also updates its native folder resource.
