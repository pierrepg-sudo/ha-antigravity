"""Per-job rootless networking. No daemon, host firewall, or unfiltered fallback.

Only this immutable launcher configures the new namespace. Commands enter the
existing AppArmor worker after all capabilities have been irreversibly dropped.
"""
import ipaddress
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys

IP = '/usr/sbin/ip'
NFT = '/usr/sbin/nft'
SLIRP = '/usr/bin/slirp4netns'
BLOCK4 = ('0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
          '169.254.0.0/16', '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24',
          '192.88.99.0/24', '192.168.0.0/16', '198.18.0.0/15',
          '198.51.100.0/24', '203.0.113.0/24', '224.0.0.0/4', '240.0.0.0/4')
# Only 2000::/3 is routable; also exclude special uses inside that allocation.
BLOCK6 = ('2001::/23', '2001:db8::/32', '2002::/16', '3fff::/20')


def run_setup(argv, stage, **kwargs):
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=8, check=False, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{stage} failed (exit {result.returncode})')
    return result.stdout


def host_policy():
    """Read addresses and resolver IPs, never credentials or environments."""
    addresses = json.loads(run_setup([IP, '-j', 'address', 'show'], 'address discovery'))
    connected = []
    for interface in addresses:
        for entry in interface.get('addr_info', []):
            if entry.get('family') in ('inet', 'inet6'):
                connected.append(str(ipaddress.ip_network(
                    f"{entry['local']}/{int(entry['prefixlen'])}", strict=False)))
    resolvers = []
    for line in Path('/etc/resolv.conf').read_text().splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == 'nameserver':
            # Scoped link-local addresses are not passed into nft syntax.
            resolvers.append(str(ipaddress.ip_address(fields[1].split('%')[0])))
    if not resolvers:
        raise RuntimeError('No DNS resolver configuration')
    return {'connected': connected, 'resolvers': resolvers}


def stub_addresses(policy):
    # These IPs are attached only to the job's loopback interface; they never
    # refer to a resolver on the real LAN. Public resolver IPs are left alone.
    addresses = {ipaddress.ip_address(value) for value in policy['resolvers']}
    if any(a.is_unspecified or a.is_multicast for a in addresses):
        raise RuntimeError('Invalid resolver address')
    return sorted((a for a in addresses if not a.is_global), key=lambda a: (a.version, int(a)))


def rules(policy):
    """Packet destination filtering, with only job-local DNS listener exceptions."""
    connected = [ipaddress.ip_network(n, strict=False) for n in policy['connected']]
    blocked4 = [str(n) for n in ipaddress.collapse_addresses(
        [ipaddress.ip_network(n) for n in BLOCK4] + [n for n in connected if n.version == 4])]
    blocked6 = [str(n) for n in ipaddress.collapse_addresses(
        [ipaddress.ip_network(n) for n in BLOCK6] + [n for n in connected if n.version == 6])]
    requests, replies = [], []
    for addr in stub_addresses(policy):
        family = 'ip' if addr.version == 4 else 'ip6'
        requests.append(f'{family} daddr {addr} meta l4proto {{ tcp, udp }} th dport 53 accept')
        replies.append(f'{family} saddr {addr} meta l4proto {{ tcp, udp }} th sport 53 ct state established accept')
    return '''table inet agy_egress {
 chain output { type filter hook output priority filter; policy drop;
  oifname "tap0" ip6 hoplimit 255 icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert } accept
  ''' + '\n  '.join('oifname "lo" ' + r for r in requests + replies) + '''
  ip daddr { ''' + ', '.join(blocked4) + ''' } reject with icmpx type admin-prohibited
  ip6 daddr != 2000::/3 reject with icmpx type admin-prohibited
  ip6 daddr { ''' + ', '.join(blocked6) + ''' } reject with icmpx type admin-prohibited
  meta l4proto { tcp, udp } accept
  reject with icmpx type admin-prohibited
 }
 chain input { type filter hook input priority filter; policy drop;
  iifname "tap0" ip6 hoplimit 255 icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert } accept
  ''' + '\n  '.join('iifname "lo" ' + r for r in requests) + '''
  ct state established,related accept
 }
 chain forward { type filter hook forward priority filter; policy drop; }
}
'''


def inside(ready_fd, label, job, command):
    if os.getuid() != 0 or Path('/proc/self/uid_map').read_text().split() != ['0', '1002', '1']:
        raise RuntimeError('Network setup requires the dedicated worker user namespace')
    os.write(int(ready_fd), b'1')
    os.close(int(ready_fd))
    # Wait until the parent has attached slirp. No user command exists yet.
    policy = json.loads(sys.stdin.buffer.readline(65536))
    if set(policy) != {'connected', 'resolvers'}:
        raise RuntimeError('Invalid network policy')
    addresses = stub_addresses(policy)
    for address in addresses:
        # 127/8 is already routed to lo; ::1 already exists. Other resolver IPs
        # are made local only inside this job, never on the host or add-on netns.
        if address.is_loopback:
            continue
        run_setup([IP, 'address', 'add', f'{address}/{address.max_prefixlen}',
                   'dev', 'lo'], 'Job-local DNS address')
    firewall = rules(policy)
    run_setup([NFT, '-f', '-'], 'namespace firewall', input=firewall.encode())
    # Bind the only permitted local service before running untrusted commands.
    # These listeners exist only inside this job's isolated network namespace.
    listeners = []
    try:
        for address in addresses:
            family = socket.AF_INET if address.version == 4 else socket.AF_INET6
            for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
                listener = socket.socket(family, kind)
                listeners.append(listener)
                if family == socket.AF_INET6:
                    listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                listener.bind((str(address), 53))
                if kind == socket.SOCK_STREAM:
                    listener.listen(8)
        dns_fds = tuple(listener.fileno() for listener in listeners)
        if dns_fds:
            subprocess.Popen(['/usr/bin/setpriv', '--bounding-set=-all', '--inh-caps=-all',
                    '--ambient-caps=-all', '--securebits=+noroot,+noroot_locked', '--no-new-privs',
                    '/usr/bin/python3', '-I', '/usr/local/bin/job_dns.py', *map(str, dns_fds)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    close_fds=True, pass_fds=dns_fds)
    finally:
        for listener in listeners:
            listener.close()
    # setpriv drops all capabilities before aa-exec, but does not set NNP early
    # (which can prevent the AppArmor transition). restricted-exec sets NNP.
    os.execv('/usr/bin/setpriv', ['setpriv', '--bounding-set=-all', '--inh-caps=-all',
             '--ambient-caps=-all', '--securebits=+noroot,+noroot_locked',
             '/usr/bin/aa-exec', '-p', label, '--', '/usr/local/bin/restricted-exec',
             label + ' (enforce)', job, command])


def outside(label, job, command):
    if os.getuid() != 1002:
        raise RuntimeError('Invalid network launcher identity')
    policy = host_policy()
    child = relay = None
    fds = set()
    def pipe():
        pair = os.pipe()
        fds.update(pair)
        return pair
    def close(fd):
        os.close(fd)
        fds.remove(fd)
    def wait_ready(fd, stage):
        if not select.select([fd], [], [], 8)[0] or os.read(fd, 1) != b'1':
            raise RuntimeError(stage + ' did not become ready')
        close(fd)
    try:
        namespace_r, namespace_w = pipe()
        child = subprocess.Popen(['/usr/bin/unshare', '--user', '--map-root-user', '--net',
                '/usr/bin/python3', '-I', __file__, '--inside', str(namespace_w), label, job, command],
                stdin=subprocess.PIPE, close_fds=True, pass_fds=(namespace_w,))
        close(namespace_w)
        wait_ready(namespace_r, 'User/network namespace')
        ready_r, ready_w = pipe()
        relay = subprocess.Popen([SLIRP, '--configure', '--enable-ipv6',
                '--disable-host-loopback', '--disable-dns', '--enable-seccomp',
                '--ready-fd=' + str(ready_w), str(child.pid), 'tap0'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True, pass_fds=(ready_w,))
        close(ready_w)
        wait_ready(ready_r, 'Temporary network relay (/dev/net/tun required)')
        child.stdin.write(json.dumps(policy).encode() + b'\n')
        child.stdin.close()
        child.stdin = None
        return child.wait()
    finally:
        for fd in fds:
            os.close(fd)
        for proc in (child, relay):
            if proc is not None:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
        if child is not None and child.stdin:
            child.stdin.close()


def main():
    try:
        if len(sys.argv) == 6 and sys.argv[1] == '--inside':
            inside(*sys.argv[2:])
        elif len(sys.argv) == 4:
            return outside(*sys.argv[1:])
        else:
            raise RuntimeError('Invalid network launcher arguments')
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        # No raw command, destination address, or subprocess stderr is logged.
        detail = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print('Restricted worker network setup: ' + detail, file=sys.stderr, flush=True)
        return 125


if __name__ == '__main__':
    sys.exit(main())
