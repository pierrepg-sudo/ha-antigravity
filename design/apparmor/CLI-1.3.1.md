> Historical investigation for releases through 0.1.23. The native mount
> exceptions and profile selection described here were removed in 0.2.0.
> See antigravity/DOCS.md for the current restricted-worker design.

# CLI 1.3.1 ARM64 mount inspection

Inspected 2026-10-08. Static inspection only: the binary was not executed, no
credentials were supplied, and no profile was loaded in the inspection environment.

Official installer: https://antigravity.google/cli/install.sh

Manifest: https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/linux_arm64.json

Payload: https://storage.googleapis.com/antigravity-public/antigravity-cli/1.3.1-4582356770750464/linux-arm/cli_linux_arm64.tar.gz

Payload SHA512 (verified before extraction):
`c41b8cd8c526eb043fa0b019377ab8109190b547624f17f5255868ace79cd8e9195a60ac7b89478101127effbe049341c4108ed0ead4b160968704a8b79d8799`

Extracted binary SHA256: `6bf15f830ecc1c42822ffa690378c53e56d154c93d80acaca342ee5afe1d6408`

The release version/architecture match the user's screenshot; the installed file's
hash has not been compared. This finding does not cover other upstream releases.
The add-on still uses the rolling installer, so future versions need revalidation.

## Verified call site

Go pclntab at file offset `0x1442400`; Go text base from the ELF module relocation
is `0x5bab0b0`. Function:
`google3/devtools/ai/sandbox/exebox.jailMain`, virtual address `0x69b0070`.

At `0x69b0458` through `0x69b0484`, the ARM64 Go register ABI arguments to
`syscall.Mount` (`0x5c94730`) are:

| Registers | Meaning | Value |
| --- | --- | --- |
| X0/X1 | source string pointer/length | 0/0: empty string |
| X2/X3 | target string pointer/length | 0x4f5595f / 8: `/dev/shm` |
| X4/X5 | filesystem pointer/length | 0x4f207f6 / 5: `tmpfs` |
| X6 | flags | 0 |
| X7/X8 | data pointer/length | 0/0: empty string |

The following error branch calls log.Fatalf with `mount tmpfs %s: %v`, producing
the user's recorded error. The earlier root propagation call uses `0x44000`
(MS_PRIVATE | MS_REC). The prerequisite unshare probe remains a separate consumer
of the profile's root propagation rules.

A later Mount call at `0x69b1964` targets the staging root plus `/dev/shm`, also
with tmpfs and zero flags. It is not covered by the new rule; no staging mount
permissions are inferred from the abbreviated error text. Native startup also
contains bind/remount operations, so this initial exception may reveal another
denial. It does not establish the full sandbox's compatibility with HAOS.

## Policy mapping and limitations

`audit mount fstype=tmpfs options=(rw) -> /dev/shm/,`

The destination is the directory lookup form. Exact options=(rw) expresses the
zero-flag read/write mount; it does not authorize bind/remount/move options.
The source is unspecified in the AppArmor rule because tmpfs has no backing
source device, and the native source is empty, not the string `tmpfs`.

This deliberately allows native zero flags; it does not assert nosuid/nodev/noexec.
The exception applies profile-wide wherever kernel namespace/capability checks
permit it. It is an outer-policy relaxation, not proof of an equally strong policy.

Offline parser validation must pass before publishing. Live success and filesystem,
network, process and credential isolation still require on-device verification.

## Staging-root call verified for 0.1.21

The target-device result after 0.1.20 is:
`sbox: mount tmpfs /dev/shm/setup/root: permission denied`.

In the same inspected binary, jailMain concatenates `/dev/shm/setup`
(pointer 0x4fe6012, length 14) and `/root` (pointer 0x4f207fb, length 5)
at 0x69b0550–0x69b056c, then saves the target at stack offsets 0x418/0x2d8.
Following directory creation, the Mount call at 0x69b06e8 has:

| Registers | Meaning | Value |
| --- | --- | --- |
| X0/X1 | source | 0/0 (empty) |
| X2/X3 | target | saved `/dev/shm/setup/root`, length 19 |
| X4/X5 | type | 0x4f207f6 / 5 (`tmpfs`) |
| X6 | flags | 0 |
| X7/X8 | data | 0/0 (empty) |

The new rule is exactly:
`audit mount fstype=tmpfs options=(rw) -> /dev/shm/setup/root/,`

It has the same profile-wide scope and zero-flag limitations described above.
It does not allow staging descendants or bind/remount operations. This is static
call-site verification plus a matching target error, not a successful sandbox run.

## Proc call verified for 0.1.23

The target device's latest diagnostic reports `sbox: mount proc: permission denied`.
In jailMain, 0x69b09c0–0x69b09d8 concatenates the stored staging root with
`/proc` (pointer 0x4f20800, length 5). The syscall.Mount call at 0x69b0a04 has:

| Registers | Meaning | Value |
| --- | --- | --- |
| X0/X1 | source | 0/0 (empty) |
| X2/X3 | target | concatenated `/dev/shm/setup/root/proc` |
| X4/X5 | type | 0x4f15c53 / 4 (`proc`) |
| X6 | flags | 0xe = MS_NOSUID (2) + MS_NODEV (4) + MS_NOEXEC (8) |
| X7/X8 | data | 0/0 (empty) |

The failure branch at 0x69b0a24 loads `mount proc: %v`. Policy mapping:
`audit mount fstype=proc options=(rw,nosuid,nodev,noexec) -> /dev/shm/setup/root/proc/,`

The existing proc deny rules now use a variable covering both @{PROC} and the
literal staged proc root, protecting proc control/sensitive files under either
path. The mount exception does not prove a fresh PID namespace or credential
isolation. It retains native flags and is subject to kernel checks; all later
unlisted mounts remain denied. No native binary was executed during inspection.
