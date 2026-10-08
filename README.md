# Antigravity Home Assistant add-on

Experimental v0.2.0. Restricted-worker runtime needs verification on HAOS.

## Install

In Home Assistant, open Settings > Apps (Add-ons) > App store > Repositories and add:

https://github.com/pierrepg-sudo/ha-antigravity

Install Antigravity Remote, start it, then select Open Web UI.

Read [setup instructions and limitations](antigravity/DOCS.md).

Version 0.2.0 replaces Chat/Balanced/Review with one managed policy. Native shell
commands are blocked. A dedicated MCP worker runs local builds and document
processing as a separate user with an AppArmor child profile and seccomp filter:
read-only inputs, writable outputs, no command networking or CLI credentials.
It must pass real isolation checks before accepting work; failure leaves commands
blocked. Existing data and user-authored permission restrictions are preserved.

After updating, restart and check **Restricted commands ready** in Open Web UI.
HAOS runtime transition and CLI MCP integration still need verification on the
device. Keep Protection mode enabled. See the setup instructions for limits.
