# Antigravity Remote 0.1.8 — experimental

This package hosts Google's Antigravity CLI, not Claude Code or the Claude iOS app.
Use your Google AI Pro account for the models and quota available to that account.
No API key is required by this wrapper. It does not enable paid overages or bypass limits.

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
/data/workspace: isolated project directory. Both are in the add-on's private data.
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

## Version 0.1.8: delete and mobile downloads

Tap Delete beside a regular file, then confirm in the dialog. Deletion is
permanent; folders and symbolic links cannot be deleted with this action.
The API also requires an explicit confirmation value and the page CSRF token.

Download now fetches the file without navigating the terminal away and opens
a save dialog. On iPhone tap Share / Save to Files, then Save to Files in the
system share sheet. If file sharing is unavailable, use Download file.
Some in-app browsers preview downloaded files even with attachment headers;
use Share > Save to Files from the preview or open Home Assistant in Safari.
The file is kept in browser memory until the dialog closes or the page reloads.
