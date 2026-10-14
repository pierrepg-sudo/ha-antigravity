"""Deny outgoing network syscalls in real-CLI test children and their descendants."""
import os
import ctypes

def block_outbound():
 lib=ctypes.CDLL('libseccomp.so.2',use_errno=True)
 lib.seccomp_init.argtypes=[ctypes.c_uint32];lib.seccomp_init.restype=ctypes.c_void_p
 lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];lib.seccomp_syscall_resolve_name.restype=ctypes.c_int
 lib.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint]
 lib.seccomp_load.argtypes=[ctypes.c_void_p];lib.seccomp_release.argtypes=[ctypes.c_void_p]
 ctx=lib.seccomp_init(0x7fff0000)
 if not ctx:os._exit(120)
 # Block all outgoing connections and datagrams in the CLI and descendants.
 # Inbound loopback HTTP accept/read/write stays available for the test client.
 for name in [b'connect',b'sendto',b'sendmsg',b'sendmmsg']:
  nr=lib.seccomp_syscall_resolve_name(name)
  if nr<0 or lib.seccomp_rule_add(ctx,0x00050000|13,nr,0)!=0:os._exit(121)
 if lib.seccomp_load(ctx)!=0:os._exit(122)
 lib.seccomp_release(ctx)

