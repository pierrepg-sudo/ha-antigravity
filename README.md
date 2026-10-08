# Antigravity Home Assistant add-on

Experimental v0.1.23. HAOS runtime and Google sign-in are not yet verified.

## Install

In Home Assistant, open Settings > Apps (Add-ons) > App store > Repositories and add:

https://github.com/pierrepg-sudo/ha-antigravity

Install Antigravity Remote, start it, then select Open Web UI.

Read [setup instructions and limitations](antigravity/DOCS.md).

Version 0.1.19 adds **Chat** mode: persistent input-read/output-write permissions,
no artifact-review pauses, and optional trusted website domains. Terminal commands,
browser actions and MCP tools still need approval. Native sandbox compatibility is
unfinished; Chat does not depend on it. Existing installations must select `chat`
in Configuration to use the new profile. Keep Protection mode on.
See [configuration and limits](antigravity/DOCS.md).

Version 0.1.21 permits the native sandbox's tmpfs mounts at exactly
`/dev/shm` and `/dev/shm/setup/root`, both with zero flags. This is a targeted startup fix, not confirmation
that the complete sandbox works. See [test instructions](antigravity/DOCS.md).

Version 0.1.22 displays a sanitized latest sandbox error in Open Web UI, with a
Refresh diagnostic button. Private CLI file permissions remain unchanged.

Version 0.1.23 also allows the verified `proc` mount at exactly
`/dev/shm/setup/root/proc` with `nosuid,nodev,noexec`, extending the existing proc
protections to this path. The full native sandbox still requires device testing.
