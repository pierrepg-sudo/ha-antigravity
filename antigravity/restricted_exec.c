/* Kernel-enforced command worker. No setuid bit, capabilities or mount operations. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <linux/capability.h>
#include <linux/securebits.h>
#include <sys/socket.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

#if defined(__x86_64__)
#define WORKER_ARCH AUDIT_ARCH_X86_64
#elif defined(__aarch64__)
#define WORKER_ARCH AUDIT_ARCH_AARCH64
#else
#error Unsupported worker architecture
#endif
#define BLOCK(n) BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, __NR_##n, 0, 1), BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|EPERM)
static _Noreturn void fail(const char *why) { fprintf(stderr, "Restricted worker unavailable: %s\n", why); exit(125); }
static void limit(int what, rlim_t value) {
    struct rlimit r = {value, value};
    if (setrlimit(what, &r)) fail("resource limit failed");
}
static void install_filter(void) {
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, WORKER_ARCH, 1, 0),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, nr)),
        /* Reject x32 and unknown high syscall namespaces as well as compat arch. */
        BPF_JUMP(BPF_JMP|BPF_JGE|BPF_K, 0x40000000U, 0, 1),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_KILL_PROCESS),
        /* Only TCP/UDP IP sockets inside the already-filtered job namespace.
         * Unix, netlink, packet/raw and other socket families cannot be opened. */
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, __NR_socket, 0, 10),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, AF_INET, 2, 0),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, AF_INET6, 1, 0),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|EPERM),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[1])),
        BPF_STMT(BPF_ALU|BPF_AND|BPF_K, ~(SOCK_CLOEXEC|SOCK_NONBLOCK)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SOCK_STREAM, 2, 0),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SOCK_DGRAM, 1, 0),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|EPERM),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW),
        /* Anonymous stream pairs support resolver/thread IPC, not local services. */
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, __NR_socketpair, 0, 11),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, AF_UNIX, 1, 0),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|EPERM),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[1])),
        BPF_STMT(BPF_ALU|BPF_AND|BPF_K, ~(SOCK_CLOEXEC|SOCK_NONBLOCK)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SOCK_STREAM, 1, 0),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|EPERM),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[2])),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, 0, 1, 0),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|EPERM),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW),
        BLOCK(listen), BLOCK(accept), BLOCK(accept4),
        BLOCK(ptrace), BLOCK(process_vm_readv), BLOCK(process_vm_writev),
        BLOCK(pidfd_getfd), BLOCK(pidfd_send_signal), BLOCK(kill), BLOCK(tkill), BLOCK(tgkill),
        BLOCK(rt_sigqueueinfo), BLOCK(rt_tgsigqueueinfo),
        BLOCK(setsid), BLOCK(setpgid), BLOCK(unshare), BLOCK(setns),
        BLOCK(mount), BLOCK(umount2), BLOCK(pivot_root), BLOCK(chroot),
        BLOCK(open_by_handle_at), BLOCK(bpf), BLOCK(perf_event_open),
        BLOCK(io_uring_setup), BLOCK(io_uring_enter), BLOCK(io_uring_register),
        BLOCK(keyctl), BLOCK(add_key), BLOCK(request_key),
        BLOCK(userfaultfd), BLOCK(reboot), BLOCK(kexec_load), BLOCK(finit_module), BLOCK(init_module), BLOCK(delete_module),
        /* Force libc to fall back to inspectable clone/fork instead of clone3. */
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, __NR_clone3, 0, 1),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|ENOSYS),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, __NR_clone, 0, 4),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[0])),
        /* Namespace creation and CLONE_PARENT are unnecessary for build tools. */
        BPF_JUMP(BPF_JMP|BPF_JSET|BPF_K, 0x7e020000U|0x00008000U, 0, 1),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|EPERM),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {sizeof(filter)/sizeof(filter[0]), filter};
    if (prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program)) fail("syscall filter failed");
}
int main(int argc, char **argv) {
    if ((argc != 4 && argc != 5) || getuid() != 0 || geteuid() != 0) fail("invalid worker identity");
    int managed = argc == 5 && !strcmp(argv[4], "managed");
    if (argc == 5 && !managed && strcmp(argv[4], "run")) fail("invalid job mode");
    if (managed && nice(10) == -1) fail("job priority failed");
    /* Namespace-root maps only to the unprivileged worker on HAOS. Never accept
     * real container root, or a namespace with additional mapped identities. */
    char mapping[128] = {0}, extra;
    unsigned inside_uid, outside_uid, count;
    int mapfd = open("/proc/self/uid_map", O_RDONLY|O_CLOEXEC);
    if (mapfd < 0) fail("cannot verify user namespace");
    ssize_t maplen = read(mapfd, mapping, sizeof(mapping)-1); close(mapfd);
    if (maplen <= 0 || sscanf(mapping, "%u %u %u %c", &inside_uid, &outside_uid, &count, &extra) != 3 ||
        inside_uid != 0 || outside_uid != 1002 || count != 1) fail("invalid user namespace");
    int secure = prctl(PR_GET_SECUREBITS);
    if (secure < 0 || (secure & (SECBIT_NOROOT|SECBIT_NOROOT_LOCKED)) !=
        (SECBIT_NOROOT|SECBIT_NOROOT_LOCKED)) fail("root capability restoration not locked");
    struct __user_cap_header_struct header = {_LINUX_CAPABILITY_VERSION_3, 0};
    struct __user_cap_data_struct caps[2] = {{0}};
    if (syscall(SYS_capget, &header, caps)) fail("cannot verify capabilities");
    for (int i=0; i<2; i++)
        if (caps[i].effective || caps[i].permitted || caps[i].inheritable) fail("capabilities not dropped");
    for (int i=0; i<=CAP_LAST_CAP; i++)
        if (prctl(PR_CAPBSET_READ, i, 0, 0, 0) != 0) fail("capability bounding set not empty");
    /* Read identity before filtering. A successful aa-exec alone is not sufficient. */
    char label[256] = {0};
    int f = open("/proc/self/attr/current", O_RDONLY|O_CLOEXEC);
    if (f < 0) fail("cannot verify AppArmor");
    ssize_t n = read(f, label, sizeof(label)-1); close(f);
    if (n <= 0) fail("cannot verify AppArmor");
    label[strcspn(label, "\n")] = 0;
    if (strcmp(label, argv[1]) || !strstr(label, "//command_worker (enforce)")) fail("worker confinement not enforced");
    if (strncmp(argv[2], "/tmp/agy-worker/job-", 20) || strchr(argv[2]+20, '/')) fail("invalid temporary directory");
    if (chdir("/data/workspace/outputs")) fail("output directory unavailable");
    if (clearenv() || setenv("PATH", "/usr/bin:/bin", 1) ||
        setenv("HOME", argv[2], 1) || setenv("TMPDIR", argv[2], 1) ||
        setenv("XDG_CACHE_HOME", argv[2], 1) || setenv("LANG", "C.UTF-8", 1)) fail("environment setup failed");
    umask(0007);
    limit(RLIMIT_CORE, 0); limit(RLIMIT_CPU, managed ? 86400 : 60); limit(RLIMIT_AS, 512UL*1024*1024);
    limit(RLIMIT_FSIZE, 32UL*1024*1024); limit(RLIMIT_NOFILE, 128); limit(RLIMIT_NPROC, 32);
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) fail("no-new-privileges failed");
    /* Only pipes/null remain: never inherit the broker socket or an open secret. */
    if (syscall(SYS_close_range, 3U, ~0U, 0)) fail("descriptor isolation failed");
    install_filter();
    execl("/bin/bash", "bash", "--noprofile", "--norc", "-c", argv[3], (char *)NULL);
    fail("cannot execute shell");
}
