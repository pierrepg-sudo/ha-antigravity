"""Apply the single managed policy and restricted MCP tool before CLI startup."""
import json
import ipaddress
import re
import os
from pathlib import Path
import tempfile

ALLOW = ['read_file(/data/inputs)', 'write_file(/data/workspace/outputs)',
         'mcp(ha-restricted-worker/run)']
DENY = ['write_file(/data/inputs)', 'read_file(/data/home/.ssh)',
        'read_file(/data/home/.gemini/antigravity-cli)',
        'read_file(/data/home/.gemini/config)',
        'write_file(/data/home)', 'write_file(/run/antigravity)',
        'command(*)', 'unsandboxed(*)', 'read_file(/run/antigravity-files)',
        'write_file(/opt/antigravity-workspace)']
ASK = ['execute_url(*)']


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


def prepare(path, domains=None):
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
    backup = path.with_name('settings.before-restricted-worker.json')
    if not backup.exists():
        atomic_json(backup, settings)
    settings.update(enableTerminalSandbox=False,
                    toolPermission='request-review',
                    allowNonWorkspaceAccess=False,
                    artifactReviewPolicy='always-proceed')
    if settings.get('altScreenMode', 'default') == 'default':
        settings['altScreenMode'] = 'never'
    # Replace all prior grants; retain user-authored restrictions. Our own previous
    # ask rules are replaced when upgrading the policy; user restrictions survive.
    state_path = path.with_name('ha-managed-permissions.json')
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    previous_ask = previous.get('addedAsk', []) if isinstance(previous, dict) else []
    ask = [x for x in permissions.get('ask', []) if x not in previous_ask]
    required_ask = list(ASK)
    added_ask = [x for x in required_ask if x not in ask]
    settings['permissions'] = {
        'allow': list(ALLOW) + [f'read_url({domain})' for domain in domains],
        'deny': list(dict.fromkeys(permissions.get('deny', []) + DENY)),
        'ask': list(dict.fromkeys(ask + required_ask)),
    }
    atomic_json(path, settings)
    atomic_json(state_path, {'addedAsk': added_ask})
    # The fixed CLI workspace is root-owned: generated outputs cannot install
    # auto-loaded workspace hooks or MCP configurations into the active workspace.
    config_path = path.parent.parent / 'config/mcp_config.json'
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    if not isinstance(config, dict) or not isinstance(config.get('mcpServers', {}), dict):
        raise ValueError('Invalid MCP configuration')
    config.setdefault('mcpServers', {})['ha-restricted-worker'] = {
        'command': '/usr/bin/python3', 'args': ['-I', '/usr/local/bin/worker_mcp.py']}
    atomic_json(config_path, config)
    return {'message': 'One managed policy: native shell blocked; use the restricted worker for commands.',
            'trustedReadDomains': domains}


if __name__ == '__main__':
    try:
        domains = json.loads(Path('/run/antigravity/trusted-read-domains.json').read_text())
        status = prepare(Path.home() / '.gemini/antigravity-cli/settings.json', domains=domains)
        print(status['message'], flush=True)
    except (OSError, ValueError):
        raise SystemExit('Cannot apply managed permissions. CLI startup stopped; check settings and add-on options.')
