"""MCP stdio adapter: pass commands to the separate-UID broker, never execute here."""
import json
import socket
import sys

SOCKET = '/run/antigravity-worker/worker.sock'
TOOL = {'name': 'run',
        'description': 'Run local C/C++ builds, Python, Pandoc/PDF generation and file processing in the restricted worker. Working directory: /data/workspace/outputs. Read originals from /data/inputs. Public outbound TCP/UDP internet is allowed. Private/local networks, inbound listeners, CLI credentials, private CLI files and interactive/background sessions are blocked. Maximum 90 seconds, 256 KiB output, 32 MiB per file. Use this instead of the blocked native terminal tool.',
        'inputSchema': {'type': 'object', 'properties': {'command': {'type': 'string', 'maxLength': 32768}},
                        'required': ['command'], 'additionalProperties': False}}


def dispatch(request):
    method = request.get('method')
    params = request.get('params', {})
    if method == 'initialize':
        return {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                'serverInfo': {'name': 'ha-restricted-worker', 'version': '0.2.4'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': [TOOL]}
    if method == 'tools/call':
        if params.get('name') != 'run':
            raise ValueError('Unknown tool')
        args = params.get('arguments', {})
        if not isinstance(args, dict) or set(args) != {'command'} or not isinstance(args['command'], str):
            raise ValueError('Expected command text')
        if not args['command'].strip() or len(args['command'].encode()) > 32768 or '\x00' in args['command']:
            raise ValueError('Invalid command')
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(100)
                connection.connect(SOCKET)
                connection.sendall(json.dumps(args).encode()+b'\n')
                with connection.makefile('rb') as stream:
                    data = stream.readline(2*1024*1024)
                response = json.loads(data)
            return {'content': [{'type': 'text', 'text': json.dumps(response)}],
                    'isError': bool(response.get('error') or response.get('timedOut') or response.get('exitCode') != 0)}
        except (OSError, ValueError):
            return {'content': [{'type': 'text', 'text': 'Restricted worker unavailable. No command was run; there is no native shell fallback.'}], 'isError': True}
    raise ValueError('Unsupported method')


def main():
    while True:
        line = sys.stdin.buffer.readline(65537)
        if not line:
            return
        if len(line) > 65536 or not line.endswith(b'\n'):
            return
        request = {}
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                return
            if 'id' not in request:
                continue
            response = {'jsonrpc': '2.0', 'id': request['id'], 'result': dispatch(request)}
        except (ValueError, TypeError, AttributeError):
            response = {'jsonrpc': '2.0', 'id': request.get('id'),
                        'error': {'code': -32602, 'message': 'Invalid or unsupported request'}}
        print(json.dumps(response), flush=True)


if __name__ == '__main__':
    main()
