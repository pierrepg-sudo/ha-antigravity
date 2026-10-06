# Changelog

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
