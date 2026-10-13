"""Admin-ingress setup for the official remote GitHub MCP server. No shell auth."""
import json
import re
import threading
import time
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError, URLError

SERVER = 'ha-github'
ENDPOINT = 'https://api.githubcopilot.com/mcp/'
TOOLS = ('get_me', 'get_file_contents', 'get_commit', 'list_commits',
         'list_branches', 'push_files', 'delete_file')
GRANTS = ['mcp('+SERVER+'/'+tool+')' for tool in TOOLS]
LOCK = threading.Lock()
LIMIT = 1024 * 1024
DOMAINS_PATH = Path('/run/antigravity/trusted-read-domains.json')


class ConnectionError(ValueError):
    """Only fixed, non-secret diagnostics may reach the UI."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def entry(token):
    return {'serverUrl': ENDPOINT, 'headers': {
        'Authorization': 'Bearer '+token, 'X-MCP-Tools': ','.join(TOOLS)}}


def paths(home):
    config = Path(home)/'.gemini/config'
    return config/'mcp_config.json', config/'ha-github-connection.json'


def read_files(home):
    from prepare_settings import read_config
    path, state_path = paths(home)
    config = read_config(path, 'Global MCP configuration', allow_empty=True)
    state = read_config(state_path, 'GitHub connection state')
    if not isinstance(config, dict) or not isinstance(config.get('mcpServers', {}), dict) or not isinstance(state, dict):
        raise ConnectionError('Invalid saved GitHub configuration. No changes made.')
    return config, state


def active(config, state):
    saved = config.get('mcpServers', {}).get(SERVER)
    if not state.get('managed') or not isinstance(saved, dict):
        return False
    auth = saved.get('headers', {}).get('Authorization', '') if isinstance(saved.get('headers'), dict) else ''
    return (isinstance(auth, str) and auth.startswith('Bearer github_pat_') and
            saved == entry(auth[7:]))


def enabled(home):
    config, state = read_files(home)
    return active(config, state)


def status(home=None):
    config, state = read_files(Path.home() if home is None else home)
    connected = active(config, state)
    return {'configured': connected, 'account': state.get('account', '') if connected else '',
            'verified_at': state.get('verified_at') if connected else None,
            'message': ('GitHub configuration saved. Reload/restart the CLI to apply it. Last connection check succeeded; this is not a live status check.'
                        if connected else 'GitHub is not configured through this setup.')}


def request(url, token, payload=None, headers=None):
    # Fixed destinations only; neither proxy environment nor redirects may receive credentials.
    if url not in ('https://api.github.com/user', ENDPOINT):
        raise ConnectionError('Unsupported GitHub endpoint.')
    request_headers = {'Authorization': 'Bearer '+token, 'User-Agent': 'HA-Antigravity-GitHub-Setup',
                       'Accept': 'application/json'}
    if headers:
        request_headers.update(headers)
    body = None if payload is None else json.dumps(payload).encode()
    if body is not None:
        request_headers['Content-Type'] = 'application/json'
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(Request(url, data=body, headers=request_headers), timeout=12) as response:
            data = response.read(LIMIT+1)
            if len(data) > LIMIT:
                raise ConnectionError('GitHub returned an oversized response.')
            return data, dict(response.headers)
    except HTTPError as error:
        code = error.code
        error.close()
        if code == 401:
            raise ConnectionError('GitHub rejected the token. Check its value and expiry.') from None
        if code == 403:
            raise ConnectionError('GitHub denied access. Check token permissions, organization approval and rate limits.') from None
        raise ConnectionError('GitHub connection failed. No credentials were saved by this check.') from None
    except (URLError, OSError, TimeoutError):
        raise ConnectionError('Cannot reach GitHub. Check internet access and try again.') from None


def rpc_data(data, expected_id):
    try:
        text = data.decode('utf-8')
        messages = ([json.loads(text)] if text.lstrip().startswith('{') else
                    [json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith('data:')])
        result = next(message for message in messages if isinstance(message, dict) and message.get('id') == expected_id)
        if 'error' in result or not isinstance(result.get('result'), dict):
            raise ValueError()
        return result['result']
    except (ValueError, StopIteration, UnicodeError):
        raise ConnectionError('GitHub MCP returned an unexpected response. No configuration saved.') from None


def verify(token):
    if not isinstance(token, str) or not re.fullmatch(r'github_pat_[A-Za-z0-9_]{20,240}', token):
        raise ConnectionError('Enter a fine-grained GitHub personal access token beginning with github_pat_.')
    raw, _ = request('https://api.github.com/user', token)
    try:
        login = json.loads(raw)['login']
        if not isinstance(login, str) or not re.fullmatch('[A-Za-z0-9-]{1,100}', login):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ConnectionError('GitHub account could not be verified.') from None
    headers = {'Accept': 'application/json, text/event-stream', 'X-MCP-Tools': ','.join(TOOLS)}
    raw, response_headers = request(ENDPOINT, token, {'jsonrpc':'2.0', 'id':1, 'method':'initialize',
        'params':{'protocolVersion':'2024-11-05', 'capabilities':{},
                  'clientInfo':{'name':'ha-antigravity-setup','version':'0.8.1'}}}, headers)
    initialized = rpc_data(raw, 1)
    protocol = initialized.get('protocolVersion')
    if protocol not in ('2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25'):
        raise ConnectionError('GitHub MCP negotiated an unsupported protocol version.')
    headers['MCP-Protocol-Version'] = protocol
    session = next((v for k, v in response_headers.items() if k.lower() == 'mcp-session-id'), None)
    if session:
        if len(session) > 1024 or not re.fullmatch(r'[\x21-\x7e]+', session):
            raise ConnectionError('Invalid GitHub MCP session response.')
        headers['Mcp-Session-Id'] = session
    request(ENDPOINT, token, {'jsonrpc':'2.0','method':'notifications/initialized'}, headers)
    raw, _ = request(ENDPOINT, token, {'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}, headers)
    tools = rpc_data(raw, 2).get('tools', [])
    if not isinstance(tools, list):
        raise ConnectionError('GitHub tool discovery failed.')
    names = {t.get('name') for t in tools if isinstance(t, dict) and isinstance(t.get('name'), str)}
    if not {'get_file_contents', 'push_files'} <= names or names - set(TOOLS):
        raise ConnectionError('Required repository tools are missing or extra tools were returned. Check Contents read/write permission and server compatibility.')
    return login


def action(payload, home=None):
    from prepare_settings import write_config, prepare, read_config
    home = Path.home() if home is None else Path(home)
    with LOCK:
        if payload == {'action': 'status'}:
            return status(home)
        if payload.get('action') == 'connect' and set(payload) == {'action', 'token', 'authorize'} and payload['authorize'] is True:
            token = payload['token']
            login = verify(token)  # Read-only preflight; never create a test commit.
            config, state = read_files(home)
            if SERVER in config.get('mcpServers', {}) and not state.get('managed'):
                raise ConnectionError('An unmanaged ha-github entry already exists. It was not overwritten.')
            config.setdefault('mcpServers', {})[SERVER] = entry(token)
            state = {'managed': True, 'account': login, 'verified_at': int(time.time())}
        elif payload == {'action': 'disconnect', 'confirm': True}:
            config, state = read_files(home)
            if SERVER in config.get('mcpServers', {}) and not state.get('managed'):
                raise ConnectionError('The ha-github entry is not owned by this setup. No changes made.')
            config.get('mcpServers', {}).pop(SERVER, None)
            state = {}
        elif payload == {'action': 'test'}:
            config, state = read_files(home)
            if not active(config, state):
                raise ConnectionError('Connect GitHub first.')
            login = verify(config['mcpServers'][SERVER]['headers']['Authorization'][7:])
            return {'ok':True, 'message':'GitHub account '+login+' and repository MCP tools verified. No repository changes made.'}
        else:
            raise ConnectionError('Invalid GitHub setup request.')
        config_path, state_path = paths(home)
        domains = read_config(DOMAINS_PATH, 'Trusted domains', optional=False)
        settings_path = home/'.gemini/antigravity-cli/settings.json'
        # Validate policy first and preserve the pre-connection config privately.
        prepare(settings_path, domains)
        from prepare_settings import backup_mcp
        backup_mcp(config_path)
        # Preserve the worker entry installed by prepare on a fresh profile.
        current, _ = read_files(home)
        config.setdefault('mcpServers', {})['ha-restricted-worker'] = current['mcpServers']['ha-restricted-worker']
        # Existing MCP entries are preserved. Tokens are never copied to workspace or env.
        write_config(config_path, config, 'GitHub MCP configuration')
        write_config(state_path, state, 'GitHub connection state')
        prepare(settings_path, domains)
        result = status(home)
        result['ok'] = True
        if not state:
            result['message'] = 'Saved GitHub credentials removed. Restart the CLI to discard any cached connection. Revoke the token in GitHub for immediate invalidation.'
        return result
