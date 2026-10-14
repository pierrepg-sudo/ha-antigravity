# Antigravity Home Assistant add-on

Experimental v0.9.9. Public egress requires a successful HAOS startup isolation check.

## Install

In Home Assistant, open Settings > Apps (Add-ons) > App store > Repositories and add:

https://github.com/pierrepg-sudo/ha-antigravity

Install Antigravity Remote, start it, then select Open Web UI.

Read [setup instructions and limitations](antigravity/DOCS.md).

The managed policy replaces Chat/Balanced/Review with one managed policy. Native shell
commands are blocked. A dedicated MCP worker runs local builds and document
processing as a separate user with an AppArmor child profile and seccomp filter:
read-only inputs, writable outputs, public outbound TCP/UDP, and no CLI credentials.
Each command has a temporary network namespace and firewall blocking private/local
destinations. The network and DNS helpers end with the job; no persistent agent
service is installed.
It must pass real isolation checks before accepting work; failure leaves commands
blocked. Existing data and user-authored permission restrictions are preserved.

After updating, restart and check **Restricted commands ready** in Open Web UI.
This version adds `/dev/net/tun` access without host networking or additional host
capabilities. Keep Protection mode enabled. Namespace/firewall compatibility and
public connectivity must be verified on the device. See the setup instructions
for DNS behavior and the unchanged 90-second short-command limit.
Managed jobs support opt-in recovery after add-on/HAOS restarts; see the restart
policy documentation. No existing job is automatically opted in.

Connect GitHub from **Open Web UI → GitHub** using a fine-grained token restricted
to your selected repositories with Contents read/write permission. The form verifies
and saves the official GitHub MCP connection; restart afterward. No marketplace
plugin is required. Tokens belong in the setup form, never in chat. Publishing
instructions default to local checks, authorized changes directly to main and
no Actions workflows.

The Files tool supports folder ZIP downloads and Copy → Paste for files and folders.
Use Move → Paste within Inputs or Outputs. Existing names are never overwritten.
