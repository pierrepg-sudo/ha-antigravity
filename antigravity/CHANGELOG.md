# Changelog

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
