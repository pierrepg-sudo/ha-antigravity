"""Policy and fail-closed orchestration tests; no claim of a live HAOS firewall."""
import io
import ipaddress
import json
import re
import unittest
from unittest.mock import patch, Mock
from test_mobile import m
import network_job as network
import job_dns


class NetworkTests(unittest.TestCase):
    def test_private_destinations_and_connected_public_subnet_are_rejected(self):
        policy = {'connected': ['10.0.2.0/24', '172.30.32.0/23', '8.8.8.0/24',
                                '2606:4700:ffff::/64'], 'resolvers': ['127.0.0.11']}
        text = network.rules(policy)
        sets = re.findall(r'ip(6?) daddr \{ ([^}]+) \} jump reject[46]', text)
        prefixes = {family: [ipaddress.ip_network(x.strip()) for x in values.split(',')]
                    for family, values in sets}
        for value in ['0.0.0.0', '10.1.2.3', '100.64.1.1', '127.0.0.1',
                      '169.254.169.254', '172.30.32.1', '192.168.1.1',
                      '198.18.0.1', '224.0.0.1', '255.255.255.255', '8.8.8.8']:
            self.assertTrue(any(ipaddress.ip_address(value) in n for n in prefixes['']), value)
        self.assertFalse(any(ipaddress.ip_address('1.1.1.1') in n for n in prefixes['']))
        self.assertTrue(any(ipaddress.ip_address('2606:4700:ffff::1') in n for n in prefixes['6']))
        self.assertIn('ip6 daddr != 2000::/3 jump reject6', text)
        # Avoid conflicting/overlapping nft interval sets.
        for networks in prefixes.values():
            for i, a in enumerate(networks):
                for b in networks[i+1:]:
                    self.assertFalse(a.overlaps(b))
        self.assertLess(text.index('ip daddr {'), text.index('meta l4proto { tcp, udp } accept'))

    def test_dns_exceptions_are_only_job_local_port_53(self):
        text = network.rules({'connected': [], 'resolvers': ['172.30.32.3', '::1', '8.8.8.8']})
        exceptions = [line.strip() for line in text.splitlines() if 'dport 53 accept' in line]
        self.assertEqual(len(exceptions), 4)
        self.assertTrue(all('ifname "lo"' in line for line in exceptions))
        self.assertTrue(all('172.30.32.3' in line or '::1' in line for line in exceptions))
        self.assertFalse(any('8.8.8.8' in line for line in exceptions))
        self.assertNotIn('dnat', text)
        self.assertEqual(job_dns.UPSTREAM, ('1.1.1.1', 53))

    def test_untrusted_syntax_cannot_enter_firewall(self):
        for value in ['1.1.1.1; flush ruleset', 'example.com', '127.0.0.1\naccept']:
            with self.assertRaises(ValueError):
                network.rules({'connected': [], 'resolvers': [value]})

    def test_firewall_failure_never_starts_dns_or_command(self):
        policy = json.dumps({'connected': [], 'resolvers': ['127.0.0.11']}).encode() + b'\n'
        stdin = Mock(buffer=io.BytesIO(policy))
        with patch.object(network.os, 'getuid', return_value=0), \
             patch.object(network.Path, 'read_text', return_value='0 1002 1'), \
             patch.object(network.sys, 'stdin', stdin), patch.object(network.os, 'write'), \
             patch.object(network.os, 'close'), patch.object(network, 'run_setup', side_effect=RuntimeError('firewall failed')), \
             patch.object(network.subprocess, 'Popen') as spawn, patch.object(network.os, 'execv') as execute:
            with self.assertRaisesRegex(RuntimeError, 'firewall failed'):
                network.inside('3', 'label', 'job', 'SECRET COMMAND')
            spawn.assert_not_called()
            execute.assert_not_called()

    def test_namespace_failure_cleans_child_and_never_starts_relay(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(network.os, 'getuid', return_value=1002), \
             patch.object(network, 'host_policy', return_value={'connected': [], 'resolvers': []}), \
             patch.object(network.subprocess, 'Popen', return_value=process) as spawn, \
             patch.object(network.select, 'select', return_value=([], [], [])):
            with self.assertRaisesRegex(RuntimeError, 'namespace'):
                network.outside('label', 'job', 'COMMAND')
            self.assertEqual(spawn.call_count, 1)
            process.kill.assert_called_once()
            process.wait.assert_called_once()
            process.stdin.close.assert_called_once()

    def test_timeout_requires_kernel_reject_evidence(self):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.connect.side_effect = TimeoutError()
        connection.sendto.side_effect = TimeoutError()
        with patch.object(network.socket, 'socket', return_value=connection), \
             patch.object(network, 'rejected_packets', return_value=0):
            with self.assertRaisesRegex(RuntimeError, 'reject counter unchanged'):
                network.verify_destination_filter()
        # Ten probes, independent before/after readings for each.
        with patch.object(network.socket, 'socket', return_value=connection), \
             patch.object(network, 'rejected_packets', side_effect=[0, 1] * 10):
            network.verify_destination_filter()

    def test_udp_enqueue_is_not_confused_with_packet_delivery(self):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.connect.side_effect = TimeoutError()
        connection.sendto.return_value = len(b'worker-check')
        with patch.object(network.socket, 'socket', return_value=connection), \
             patch.object(network, 'rejected_packets', side_effect=[0, 1] * 10):
            network.verify_destination_filter()
        # TCP was rejected, but the first UDP packet lacks rejection evidence.
        with patch.object(network.socket, 'socket', return_value=connection), \
             patch.object(network, 'rejected_packets', side_effect=[0, 1, 0, 0]):
            with self.assertRaisesRegex(RuntimeError, 'udp .*reject counter unchanged'):
                network.verify_destination_filter()

    def test_successful_tcp_connection_is_always_failure(self):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        with patch.object(network.socket, 'socket', return_value=connection), \
             patch.object(network, 'rejected_packets', side_effect=[0, 1]):
            with self.assertRaisesRegex(RuntimeError, 'TCP connected'):
                network.verify_destination_filter()

    def test_counter_missing_or_wrong_identity_is_failure(self):
        for response in ({'nftables': []}, {'nftables': [{'counter': {
                'family': 'inet', 'table': 'other', 'name': 'blocked4_tcp', 'packets': 99}}]}):
            with patch.object(network, 'run_setup', return_value=json.dumps(response).encode()):
                with self.assertRaisesRegex(RuntimeError, 'counter response invalid'):
                    network.rejected_packets('blocked4_tcp')

    def test_filter_verification_failure_never_launches_command(self):
        policy = json.dumps({'connected': [], 'resolvers': ['127.0.0.11']}).encode() + b'\n'
        with patch.object(network.os, 'getuid', return_value=0), \
             patch.object(network.Path, 'read_text', return_value='0 1002 1'), \
             patch.object(network.sys, 'stdin', Mock(buffer=io.BytesIO(policy))), \
             patch.object(network.os, 'write'), patch.object(network.os, 'close'), \
             patch.object(network, 'run_setup'), \
             patch.object(network, 'verify_destination_filter', side_effect=RuntimeError('unverified')), \
             patch.object(network.subprocess, 'Popen') as spawn, patch.object(network.os, 'execv') as execute:
            with self.assertRaisesRegex(RuntimeError, 'unverified'):
                network.inside('3', 'label', 'job', 'COMMAND')
            spawn.assert_not_called()
            execute.assert_not_called()

    def test_dns_tcp_frame_reader_handles_fragmentation_and_truncation(self):
        connection = Mock()
        connection.recv.side_effect = [b'a', b'bc', b'd']
        self.assertEqual(job_dns.exactly(connection, 4), b'abcd')
        connection.recv.side_effect = [b'a', b'']
        with self.assertRaises(OSError):
            job_dns.exactly(connection, 4)


if __name__ == '__main__':
    unittest.main()
