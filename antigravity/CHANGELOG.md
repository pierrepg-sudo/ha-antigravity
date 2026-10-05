# Changelog

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
