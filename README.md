# Antigravity Home Assistant add-on

Experimental v0.1.18. HAOS runtime and Google sign-in are not yet verified.

## Install

In Home Assistant, open Settings > Apps (Add-ons) > App store > Repositories and add:

https://github.com/pierrepg-sudo/ha-antigravity

Install Antigravity Remote, start it, then select Open Web UI.

Read [setup instructions and limitations](antigravity/DOCS.md).

Version 0.1.18 is a **stage-one AppArmor test build**. It installs an add-on-specific
profile allowing only private root mount propagation in addition to its compatibility
baseline. **Commands still require approval**, even if the namespace probe passes.
The CLI refuses to start unless the add-on profile is enforced. Read the
[upgrade/test instructions](antigravity/DOCS.md) before updating.
