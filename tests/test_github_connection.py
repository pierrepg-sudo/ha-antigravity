import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import github_connection as github
import prepare_settings as policy
from test_mobile import m

TOKEN = 'github_pat_' + 'a' * 30


class GitHubTests(unittest.TestCase):
    def test_lifecycle_preserves_other_servers_and_never_backs_up_token(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            domains = home/'domains.json'; domains.write_text('[]')
            config_path, state_path = github.paths(home)
            config_path.parent.mkdir(parents=True)
            original = {'mcpServers': {'existing': {'command': 'existing'}}}
            config_path.write_text(json.dumps(original))
            settings = home/'.gemini/antigravity-cli/settings.json'
            settings.parent.mkdir(); settings.write_text(json.dumps({'permissions': {'ask': ['mcp(*)']}}))
            with patch.object(github, 'DOMAINS_PATH', domains), patch.object(github, 'verify', return_value='example'):
                result = github.action({'action': 'connect', 'token': TOKEN, 'authorize': True}, home)
                self.assertTrue(result['configured'])
                self.assertNotIn(TOKEN, json.dumps(result))
                self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
                saved = json.loads(config_path.read_text())
                self.assertEqual(saved['mcpServers']['existing'], original['mcpServers']['existing'])
                self.assertEqual(saved['mcpServers'][github.SERVER], github.entry(TOKEN))
                policy.prepare(settings)
                permissions = json.loads(settings.read_text())['permissions']
                self.assertTrue(set(github.GRANTS) <= set(permissions['allow']))
                self.assertIn('mcp(*)', permissions['ask'])
                for backup in home.rglob('*before*'):
                    self.assertNotIn(TOKEN, backup.read_text())
                self.assertTrue(github.action({'action': 'test'}, home)['ok'])
                self.assertFalse(github.action({'action': 'disconnect', 'confirm': True}, home)['configured'])
                self.assertNotIn(TOKEN, config_path.read_text())
                self.assertNotIn(github.SERVER, json.loads(config_path.read_text())['mcpServers'])
                self.assertEqual(json.loads(settings.read_text())['permissions']['allow'], policy.ALLOW)
                self.assertIn('existing', json.loads(config_path.read_text())['mcpServers'])

    def test_fresh_install_does_not_copy_token_to_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); domains = home/'domains.json'; domains.write_text('[]')
            with patch.object(github, 'DOMAINS_PATH', domains), patch.object(github, 'verify', return_value='example'):
                github.action({'action':'connect','token':TOKEN,'authorize':True}, home)
            self.assertTrue(github.enabled(home))
            for backup in home.rglob('*before*'):
                self.assertNotIn(TOKEN, backup.read_text())

    def test_failed_verification_and_missing_consent_do_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.object(github, 'verify', side_effect=github.ConnectionError('Token rejected.')) as verify:
                for payload in ({'action':'connect','token':TOKEN,'authorize':False},
                                {'action':'connect','token':TOKEN},
                                {'action':'disconnect'}, {'action':'connect','token':TOKEN,'authorize':True}):
                    with self.assertRaises(github.ConnectionError):github.action(payload, home)
                self.assertEqual(verify.call_count, 1)
            self.assertEqual(list(home.iterdir()), [])

    def test_unmanaged_entry_and_changed_endpoint_never_auto_granted(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); config, state = github.paths(home)
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'mcpServers':{github.SERVER:github.entry(TOKEN)}}))
            with patch.object(github, 'verify', return_value='example'):
                with self.assertRaises(github.ConnectionError):
                    github.action({'action':'connect','token':TOKEN,'authorize':True},home)
                with self.assertRaises(github.ConnectionError):
                    github.action({'action':'disconnect','confirm':True},home)
            state.write_text('{"managed": true}')
            changed = github.entry(TOKEN); changed['serverUrl']='https://example.com'
            config.write_text(json.dumps({'mcpServers':{github.SERVER:changed}}))
            settings=home/'.gemini/antigravity-cli/settings.json'
            policy.prepare(settings)
            self.assertEqual(json.loads(settings.read_text())['permissions']['allow'],policy.ALLOW)

    def test_mcp_handshake_and_scoped_discovery(self):
        def responses(extra=False):
            return [(b'{"login":"example"}', {}),
                    (b'{"id":1,"result":{"protocolVersion":"2025-03-26"}}', {'mcp-session-id':'session'}),
                    (b'', {}),
                    (('data: '+json.dumps({'id':2,'result':{'tools':[{'name':name} for name in list(github.TOOLS)+(['run_workflow'] if extra else [])]}})+'\n\n').encode(), {})]
        with patch.object(github,'request',side_effect=responses()) as request:
            self.assertEqual(github.verify(TOKEN),'example')
            self.assertEqual(request.call_args.args[3]['Mcp-Session-Id'],'session')
            self.assertEqual(request.call_args.args[3]['X-MCP-Tools'],','.join(github.TOOLS))
        with patch.object(github,'request',side_effect=responses(True)):
            with self.assertRaises(github.ConnectionError):github.verify(TOKEN)
        for token in ('bad',TOKEN+'\r\nOther: x',None):
            with self.assertRaises(github.ConnectionError):github.verify(token)

    def test_transport_redacts_errors_and_disables_redirects_and_proxies(self):
        error=HTTPError(github.ENDPOINT,403,TOKEN,{},io.BytesIO(TOKEN.encode()))
        with patch.object(github,'build_opener') as builder:
            builder.return_value.open.side_effect=error
            with self.assertRaises(github.ConnectionError) as failure:github.request(github.ENDPOINT,TOKEN)
            self.assertNotIn(TOKEN,str(failure.exception))
            self.assertEqual(builder.call_args.args[0].proxies,{})
            self.assertIsNone(builder.call_args.args[1].redirect_request(None,None,302,'',{},'https://other.example'))
        with self.assertRaises(github.ConnectionError):github.request('https://other.example',TOKEN)

    def test_http_requires_csrf_and_redacts_errors(self):
        server=m.ThreadingHTTPServer(('127.0.0.1',0),m.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urlopen(base+'/github') as response:
                body=response.read().decode()
                self.assertIn(m.CSRF,body)
                self.assertIn('type="password"',body)
                self.assertEqual(response.headers['Cache-Control'],'no-store')
            with patch.object(github,'action',return_value={'configured':False}) as action:
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/github-action',data=b'{}',headers={'Content-Type':'application/json'}))
                self.assertEqual(error.exception.code,403);action.assert_not_called()
                with urlopen(Request(base+'/github-action',data=b'{"action":"status"}',headers={'Content-Type':'application/json','X-Antigravity-CSRF':m.CSRF})) as response:
                    self.assertFalse(json.load(response)['configured'])
                action.assert_called_once_with({'action':'status'})
            with patch.object(github,'action',side_effect=ValueError(TOKEN)):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/github-action',data=b'{}',headers={'Content-Type':'application/json','X-Antigravity-CSRF':m.CSRF}))
                self.assertNotIn(TOKEN,error.exception.read().decode())
        finally:
            server.shutdown();server.server_close();thread.join()
