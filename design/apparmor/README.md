> Historical investigation for releases through 0.1.23. The native mount
> exceptions and profile selection described here were removed in 0.2.0.
> See antigravity/DOCS.md for the current restricted-worker design.

# Antigravity add-on AppArmor design

Status: experimental policy packaged in **0.1.23** at
[`antigravity/apparmor.txt`](../../antigravity/apparmor.txt). The two root propagation
exceptions are joined by exact zero-flag tmpfs mounts at `/dev/shm/` and
`/dev/shm/setup/root/`, plus the exact `proc` mount at
`/dev/shm/setup/root/proc/` with nosuid,nodev,noexec.
[CLI 1.3.1 inspection evidence](CLI-1.3.1.md) establishes the call arguments.
This remains an incomplete native sandbox policy; other mount grants are absent.

The parser successfully compiled it with AppArmor 4.0.1 / ABI 3.0 without kernel
loading, including repository-prefixed and local profile-name variants. HAOS
runtime validation is outstanding. Command/artifact review stays enabled even
when the namespace probe succeeds, and startup refuses an unexpected profile.
See [the test and rollback instructions](../../antigravity/DOCS.md).

Supervisor source inspected at commit
`9ce1060ba7cfb833899d0ba81d8dbaf9fa4eed15` confirms that `adjust_profile` rewrites
only the profile declaration. Consequently peer rules now use `@{profile_name}`,
not the original literal declaration name. `App.hostname` derives from the full
slug with underscores replaced by hyphens; `verify_profile.py` reverses that
mapping and requires the exact `(enforce)` label. Supervisor's Docker integration
selects the full slug when the custom profile exists. The guard rejects its
possible default/unconfined fallbacks. This was source-verified, not tested on a
live Supervisor from this environment.

## Evidence and goal

The user's ARM64 HAOS device reported `docker-default (enforce)`. A user, mount,
PID and network namespace probe succeeded with `--propagation unchanged`.
Both the original probe and the native CLI failed when making the root mount
private. The native log records `sbox: mount / private: permission denied`.
The IPC reset was a subsequent symptom. Docker's standard AppArmor template
contains `deny mount,`. AppArmor is therefore a strong explanation, not an
audit-confirmed attribution: the relevant host audit events were unavailable.

Goal: permit the minimum operations needed to initialize the CLI's own sandbox
while retaining an enforced outer container policy. This design does not claim
that allowing root propagation is sufficient for a functioning native sandbox.
The native implementation's later operations and mount paths are still unknown.

## Boundary design

| Component | Planned boundary |
| --- | --- |
| HAOS host | Protection mode on; no additional Linux capabilities, host networking, device exposure, host directories, Docker socket or HA/Supervisor API access. |
| Add-on processes | One dedicated enforced AppArmor profile initially, based on the target Docker default baseline with only reviewed exceptions. |
| Root startup | Existing storage preparation only; application services still drop to separate non-root identities with no-new-privileges. |
| CLI, UID 1000 | Home for authentication/runtime; new workspace in Outputs. CLI policy grants only input reads and output writes. |
| File manager/proxy, UID 1001 | Own Inputs and the private proxy key. Existing mode bits and API authentication remain necessary. |
| Agent terminal commands | Native CLI sandbox plus approval policy. Request Review throughout validation, including when namespace preflight succeeds. |

The candidate deliberately retains Docker-style general file/network permissions
for compatibility with authentication, tmux, Nginx, compilation and PDF tools.
It is an add-on-specific mount-policy candidate, **not** a complete per-file or
per-process least-privilege redesign. It does not independently make Inputs
read-only to the agent: different UIDs, protected parents, mode bits and the file
API's private proxy key enforce that separation. A global AppArmor input-write
deny would also break the legitimate file manager, so it is not added.

Likewise the native CLI needs its own credentials and local RPC connection.
A single profile cannot distinguish the agent's intent from the CLI's legitimate
use of those credentials. Native tool sandboxing and one-time bypass decisions
remain important; no claim of total credential or network isolation is made.

## Stage one: propagation only

The proposed exceptions are exact root-target rules:

```apparmor
audit mount options=(private) -> /,
audit mount options=(rprivate) -> /,
```

`private` and `rprivate` represent the nonrecursive and recursive forms. The log
does not establish which the native CLI requests; the existing `unshare` probe
also has to be accounted for. Audit evidence should narrow these rules where
possible. Neither rule permits a bind mount, a new filesystem or a read/write
remount. Other mounts remain implicitly denied. The blanket `deny mount,` must
be absent because an explicit deny overrides an allow exception. Do not replace
it with an unrestricted `mount,` rule.

**Important limitation:** AppArmor target/option matching alone does not prove
that an operation occurs in a newly created child mount namespace. These rules
apply to every process in this candidate profile that otherwise has the kernel
permission to perform them, including the existing root startup process. Kernel
namespace ownership and capability checks still apply. This is an explicit
relaxation of the outer profile, not an equivalent-security claim or a grant
restricted by AppArmor to an authenticated sandbox setup routine.

Do not solve that limitation by granting SYS_ADMIN to the container. A separate
sandbox-setup execution profile could potentially narrow the actor, but it is
not designed here: the CLI's helper/re-exec path and no-new-privileges transition
behavior have not been verified. In particular, assigning privileges solely by
the current user-writable `agy` executable path would not establish a trusted
helper identity. A production split would need a root-owned pinned helper and
verified transitions, if upstream supports them.

## Stage two: only after further native errors identify requirements

Except for the two documented tmpfs mounts and the staged proc mount, bind mounts, temporary filesystems, proc mounts, remounts, mount moves and
pivot-root are not pre-authorized. For each required operation record:

- The native error or audit event and exact flags, source, destination and type.
- Whether the destination is under a dedicated sandbox staging directory; do not
  assume `/tmp/**` is dedicated or automatically safe.
- Whether input mounts stay read-only and only Outputs/build scratch become
  writable; check aliases and symlinks, not just path spelling.
- Whether procfs/process and network isolation remain effective.

Use exact option sets rather than `options in (...)`, and explicit source/target
pairs for any future bind mounts. Do not guess staging paths, allow arbitrary
sources under a broad target, grant writable Inputs or expose the CLI home.
If observed requirements cannot be bounded reliably, keep Review mode and
consider a separate execution host instead of expanding the HAOS policy.

## Packaging and validation gates

Before loading any candidate:

1. Reconcile the baseline against the target device's Docker profile version.
   This candidate models the reviewed upstream template, not a byte-identical
   export of the device's loaded policy. Preserve applicable protocol, proc/sys,
   signal and ptrace restrictions. Verify the host daemon signal label too.
2. Compile without loading using an AppArmor parser compatible with HAOS. Check
   the network family vocabulary, includes, flags and mount-rule encoding. Offline compilation now passes with parser 4.0.1 / ABI 3.0.
   HAOS loading and enforcement have **not** been verified.
3. Verify Supervisor's loaded profile name and any rewrite behavior. The source declaration is `antigravity_remote`; dynamic `@{profile_name}`
   signal/ptrace peers follow Supervisor's renamed label. Do not broaden peer permissions to fix an unexplained mismatch.
4. Prepare a separate experimental build using the supported add-on-local
   `apparmor.txt` mechanism; no global Docker daemon policy changes. Validate
   lifecycle and stop signals, uploads/downloads, Inputs protections, login,
   ttyd/tmux, native conversation API and normal CLI operation.
5. Force the experimental build to keep `toolPermission=request-review` and an
   explicit command ask rule. Do not reuse the current automatic balanced
   transition merely because its prerequisite probe now passes. Keep artifacts
   under review as well. A profile-load failure must prevent the experiment,
   never fall back to unconfined mode or auto-execution.
6. Run `/usr/bin/true` through the native sandbox with bypass false. Collect only
   relevant, redacted errors/audit lines. Stage one may stop at the next denied
   mount; that is a diagnostic result, not permission to widen everything.
7. Before automatic execution, verify disposable input reads/output writes,
   rejection of input modification (including rename, unlink and link aliases),
   inaccessible private credential/proxy-key fixtures, blocked unapproved local
   and external networking, restricted process visibility, and correct cleanup.
   Do not use real credentials as test data. Test C/C++ compilation and PDF
   creation with permitted scratch/cache paths. A successful `true` is not an
   isolation test.
8. Keep a previously working image available. Revert to that image and the
   default Docker profile if loading/startup or isolation checks fail; preserve
   `/data`. Do not turn Protection mode off as a rollback shortcut.

Version 0.1.23 packages root propagation, the two verified tmpfs exceptions and the staged proc mount for target-device testing. A production
policy and automatic execution can only follow the remaining isolation gates.

## Sources reviewed 2026-10-07 (Toronto)

- Home Assistant add-on profile/configuration mechanism:
  https://developers.home-assistant.io/docs/apps/configuration/
- Home Assistant security guidance:
  https://developers.home-assistant.io/docs/apps/security/
- Docker profile model and audit troubleshooting:
  https://docs.docker.com/engine/security/apparmor/
- Reviewed upstream baseline (main can change; pin the target-compatible revision
  when implementing): https://github.com/moby/profiles/blob/main/apparmor/template.go
- Exact mount-option matching and documented limitations:
  https://manpages.ubuntu.com/manpages/resolute/man5/apparmor.d.5.html
