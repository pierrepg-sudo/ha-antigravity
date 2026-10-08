"""Apply the managed permission profile before launching the CLI; fail closed."""
import json
import ipaddress
import re
import os
from pathlib import Path
import subprocess
import tempfile

ALLOW = ['read_file(/data/inputs)', 'write_file(/data/workspace/outputs)']
DENY = ['write_file(/data/inputs)', 'read_file(/data/home/.ssh)',
        'read_file(/data/home/.gemini/antigravity-cli)',
        'write_file(/data/home)', 'write_file(/run/antigravity)']
ASK = ['unsandboxed(*)', 'read_url(*)', 'execute_url(*)', 'mcp(*)']


def trusted_domains(value):
    """Accept explicit DNS hostnames only; never URLs, addresses or wildcards."""
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError('trusted_read_domains must be a list of at most 32 domains')
    result = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError('Trusted domains must be strings')
        domain = item.strip().lower()
        labels = domain.split('.')
        if (len(domain) > 253 or len(labels) < 2 or
                any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in labels) or
                labels[-1] in ('local', 'localhost', 'internal', 'lan', 'home', 'arpa') or
                not re.search(r'[a-z]', labels[-1])):
            raise ValueError('Use a public DNS hostname without a scheme, path, port or wildcard')
        try:
            ipaddress.ip_address(domain)
        except ValueError:
            pass
        else:
            raise ValueError('IP addresses cannot be trusted domains')
        if domain not in result:
            result.append(domain)
    return result


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.settings-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as target:
            json.dump(value, target, indent=2)
            target.write('\n')
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def sandbox_prerequisites():
    """Return bounded diagnostics for a fixed probe, never process environments."""
    command = ['/usr/bin/unshare', '--user', '--map-root-user', '--mount',
               '--pid', '--fork', '--net', '/usr/bin/true']
    report = {'passed': False, 'command': ' '.join(command),
              'uid': os.getuid(), 'architecture': os.uname().machine,
              'kernel': os.uname().release}
    try:
        # No inherited credentials, tool tokens, or user-controlled PATH/locale.
        result = subprocess.run(command, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, timeout=5, check=False,
                                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        report['passed'] = result.returncode == 0
        report['exitCode'] = result.returncode
        raw = result.stderr or b''
        error = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
        report['error'] = ''.join(c for c in error[:512] if c.isprintable() or c == '\n').strip()
    except subprocess.TimeoutExpired:
        report['error'] = 'Namespace probe timed out after 5 seconds.'
    except OSError as error:
        report['error'] = 'Cannot start namespace probe (errno=' + str(error.errno) + ').'
    except subprocess.SubprocessError:
        report['error'] = 'Namespace probe could not complete.'
    # Only these non-secret kernel flags are read; never dump /proc or environ.
    try:
        for line in Path('/proc/self/status').read_text().splitlines():
            key, _, value = line.partition(':')
            if key in ('NoNewPrivs', 'Seccomp', 'Seccomp_filters'):
                report[key] = value.strip()
    except OSError:
        pass
    for label, filename in (
        ('maxUserNamespaces', '/proc/sys/user/max_user_namespaces'),
        ('unprivilegedUsernsClone', '/proc/sys/kernel/unprivileged_userns_clone'),
        ('apparmorRestrictUserns', '/proc/sys/kernel/apparmor_restrict_unprivileged_userns')):
        try:
            value = Path(filename).read_text().strip()
            report[label] = int(value)
        except (OSError, ValueError):
            report[label] = 'unavailable'
    try:
        report['apparmorProfile'] = Path('/proc/self/attr/current').read_text().strip()[:160]
    except OSError:
        report['apparmorProfile'] = 'unavailable'
    report['note'] = ('This tests namespace prerequisites only. An operation-not-permitted error '
                      'does not identify whether seccomp, AppArmor, or another host restriction caused it. '
                      'No protection settings were changed.')
    return report


def prepare(path, profile='balanced', probe=sandbox_prerequisites, domains=None):
    if profile not in ('balanced', 'review', 'chat'):
        raise ValueError('Unknown permission profile')
    domains = trusted_domains([] if domains is None else domains)
    settings = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(settings, dict):
        raise ValueError('Settings must be an object')
    permissions = settings.get('permissions', {})
    if not isinstance(permissions, dict):
        raise ValueError('Permissions must be an object')
    for key in ('allow', 'deny', 'ask'):
        rules = permissions.get(key, [])
        if not isinstance(rules, list) or not all(isinstance(rule, str) for rule in rules):
            raise ValueError('Permission rules must be string lists')
    backup = path.with_name('settings.before-balanced.json')
    if not backup.exists():
        atomic_json(backup, settings)
    diagnostic = probe() if profile == 'balanced' else {'passed': False, 'note': 'Not run: ' + profile + ' profile selected.'}
    sandbox = profile == 'balanced' and diagnostic.get('passed') is True
    # Shell commands always require approval; Chat only removes artifact review.
    settings.update(enableTerminalSandbox=sandbox,
                    toolPermission='request-review',
                    allowNonWorkspaceAccess=False,
                    artifactReviewPolicy='always-proceed' if profile == 'chat' else 'asks-for-review')
    if settings.get('altScreenMode', 'default') == 'default':
        settings['altScreenMode'] = 'never'
    # Replace all prior grants; retain user-authored restrictions. Our own previous
    # ask rules are replaced when switching profiles; user restrictions survive.
    state_path = path.with_name('ha-managed-permissions.json')
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    previous_ask = previous.get('addedAsk', []) if isinstance(previous, dict) else []
    ask = [x for x in permissions.get('ask', []) if x not in previous_ask]
    required_ask = [rule for rule in ASK if profile != 'chat' or rule != 'read_url(*)'] + ['command(*)']
    added_ask = [x for x in required_ask if x not in ask]
    settings['permissions'] = {
        'allow': list(ALLOW) + ([f'read_url({domain})' for domain in domains] if profile == 'chat' else []),
        'deny': list(dict.fromkeys(permissions.get('deny', []) + DENY)),
        'ask': list(dict.fromkeys(ask + required_ask)),
    }
    atomic_json(path, settings)
    atomic_json(state_path, {'addedAsk': added_ask})
    return {'requested': profile, 'effective': 'sandbox-test' if sandbox else 'chat' if profile == 'chat' else 'review',
            'sandboxPrerequisites': 'passed' if sandbox else 'unavailable' if profile == 'balanced' else 'not-tested',
            'nativeSandboxVerified': False, 'apparmorStage': 'root-propagation-shm-and-proc', 'diagnostic': diagnostic,
            'trustedReadDomains': domains if profile == 'chat' else [],
            'message': 'Chat: input reads and output edits allowed; artifact review off. Commands require approval.' if profile == 'chat' else
                       'Sandbox test: root-propagation, shm and proc profile active; commands require approval. Native isolation is not verified.' if sandbox else
                       'Review: sandbox prerequisites unavailable; commands require approval.' if profile == 'balanced' else
                       'Review: commands require approval.'}


if __name__ == '__main__':
    try:
        profile = Path('/run/antigravity/profile').read_text().strip()
        domains_path = Path('/run/antigravity/trusted-read-domains.json')
        domains = json.loads(domains_path.read_text())
        status = prepare(Path.home() / '.gemini/antigravity-cli/settings.json', profile, domains=domains)
        atomic_json(Path('/data/home/.gemini/antigravity-cli/ha-profile-status.json'), status)
        print(status['message'], flush=True)
        print('Sandbox diagnostic: ' + json.dumps(status['diagnostic'], ensure_ascii=True), flush=True)
    except (OSError, ValueError):
        raise SystemExit('Cannot apply the permission profile. CLI startup stopped; check settings.json and add-on options.')
