"""Apply the managed permission profile before launching the CLI; fail closed."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ALLOW = ['read_file(/data/inputs)', 'write_file(/data/workspace/outputs)']
DENY = ['write_file(/data/inputs)', 'read_file(/data/home/.ssh)',
        'read_file(/data/home/.gemini/antigravity-cli)',
        'write_file(/data/home)', 'write_file(/run/antigravity)']
ASK = ['unsandboxed(*)', 'read_url(*)', 'execute_url(*)', 'mcp(*)']


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
    # Only a kernel prerequisite check, not proof of the CLI's sandbox behavior.
    try:
        result = subprocess.run(
            ['unshare', '--user', '--map-root-user', '--mount', '--pid', '--fork', '--net', 'true'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def prepare(path, profile='balanced', probe=sandbox_prerequisites):
    if profile not in ('balanced', 'review'):
        raise ValueError('Unknown permission profile')
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
    sandbox = profile == 'balanced' and probe()
    settings.update(enableTerminalSandbox=sandbox,
                    toolPermission='proceed-in-sandbox' if sandbox else 'request-review',
                    allowNonWorkspaceAccess=False,
                    artifactReviewPolicy='always-proceed' if sandbox else 'asks-for-review')
    if settings.get('altScreenMode', 'default') == 'default':
        settings['altScreenMode'] = 'never'
    # Replace all prior grants; retain user-authored restrictions. Our own previous
    # review-only wildcard is removed on a later successful balanced startup.
    state_path = path.with_name('ha-managed-permissions.json')
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    previous_ask = previous.get('addedAsk', []) if isinstance(previous, dict) else []
    ask = [x for x in permissions.get('ask', []) if x not in previous_ask]
    required_ask = ASK + ([] if sandbox else ['command(*)'])
    added_ask = [x for x in required_ask if x not in ask]
    settings['permissions'] = {
        'allow': list(ALLOW),
        'deny': list(dict.fromkeys(permissions.get('deny', []) + DENY)),
        'ask': list(dict.fromkeys(ask + required_ask)),
    }
    atomic_json(path, settings)
    atomic_json(state_path, {'addedAsk': added_ask})
    return {'requested': profile, 'effective': 'balanced' if sandbox else 'review',
            'sandboxPrerequisites': 'passed' if sandbox else 'unavailable' if profile == 'balanced' else 'not-tested',
            'nativeSandboxVerified': False,
            'message': 'Balanced: sandbox requested; native isolation still needs device verification.' if sandbox else
                       'Review: sandbox prerequisites unavailable; commands require approval.' if profile == 'balanced' else
                       'Review: commands require approval.'}


if __name__ == '__main__':
    try:
        profile = Path('/run/antigravity/profile').read_text().strip()
        status = prepare(Path.home() / '.gemini/antigravity-cli/settings.json', profile)
        atomic_json(Path('/data/home/.gemini/antigravity-cli/ha-profile-status.json'), status)
        print(status['message'], flush=True)
    except (OSError, ValueError):
        raise SystemExit('Cannot apply the permission profile. CLI startup stopped; check settings.json and add-on options.')
