# Antigravity Home Assistant add-on

Experimental v0.1.17. HAOS runtime and Google sign-in are not yet verified.

## Install

In Home Assistant, open Settings > Apps (Add-ons) > App store > Repositories and add:

https://github.com/pierrepg-sudo/ha-antigravity

Install Antigravity Remote, start it, then select Open Web UI.

Read [setup instructions and limitations](antigravity/DOCS.md).

The default **balanced** profile requests the CLI sandbox when kernel prerequisites
pass, otherwise it falls back to **review**. Files has separate **Inputs**, **Outputs**,
and **Existing files** locations. See the current profile and security limitations
in the setup instructions before relying on sandbox isolation.
