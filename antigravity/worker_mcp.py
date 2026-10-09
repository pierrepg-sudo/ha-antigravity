"""MCP stdio adapter: pass commands to the separate-UID broker, never execute here."""
import json
import socket
import sys

SOCKET = '/run/antigravity-worker/worker.sock'
TOOL = {'name': 'run',
        'description': 'Run local C/C++ builds, Python, Pandoc/PDF generation and file processing in the restricted worker. Working directory: /data/workspace/outputs. Read originals from /data/inputs. Public outbound TCP/UDP internet is allowed. Private/local networks, inbound listeners, CLI credentials, private CLI files and interactive sessions and self-detaching daemons are blocked. Use start for managed foreground jobs that need more than 90 seconds. Maximum 90 seconds, 256 KiB output, 32 MiB per file. Use this instead of the blocked native terminal tool.',
        'inputSchema': {'type': 'object', 'properties': {'command': {'type': 'string', 'maxLength': 32768}},
                        'required': ['command'], 'additionalProperties': False}}


def job_tool(name, description, properties, required):
    return {'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'properties': properties,
                            'required': required, 'additionalProperties': False}}

JOB_ID = {'job_id': {'type': 'string', 'description': 'ID returned by start or status'}}
TOOLS = [TOOL,
    job_tool('start', 'Start a managed long-running FOREGROUND command in the restricted worker. Same public-internet-only and filesystem protections as run. At most two managed jobs. Return immediately with a job ID; use status/logs to verify startup. Do not use nohup, setsid, daemon mode, PID-file launchers or shell backgrounding. No automatic restart. Jobs stop on add-on restart. stdout/stderr logs are bounded; keep secrets out of output.',
             {'command': {'type': 'string', 'maxLength': 32768},
              'name': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'}}, ['command', 'name']),
    job_tool('status', 'List managed jobs or inspect one. Running means the process is active, not that the application is healthy. Does not use arbitrary PIDs.', JOB_ID, []),
    job_tool('stop', 'Stop an owned managed job and its descendants, with a short termination grace period. Returns stopping; check status for completion.', JOB_ID, ['job_id']),
    job_tool('logs', 'Read the bounded stdout/stderr tail of an owned job. Logs may contain application secrets; redact them before displaying. Files redirected by the script are not included.', JOB_ID, ['job_id'])]


def validate(name, args):
    if not isinstance(args, dict):
        raise ValueError('Expected arguments')
    if name in ('run', 'start'):
        if set(args) != ({'command'} if name == 'run' else {'command', 'name'}):
            raise ValueError('Invalid command arguments')
        command = args['command']
        if not isinstance(command, str) or not command.strip() or len(command.encode()) > 32768 or '\x00' in command:
            raise ValueError('Invalid command')
        if name == 'start':
            import re
            if not isinstance(args['name'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args['name']):
                raise ValueError('Invalid job name')
    elif name in ('stop', 'status', 'logs'):
        if name == 'status' and not args:
            return
        if set(args) != {'job_id'} or not isinstance(args['job_id'], str) or len(args['job_id']) != 32:
            raise ValueError('Expected job_id')
    else:
        raise ValueError('Unknown tool')


def dispatch(request):
    method = request.get('method')
    params = request.get('params', {})
    if method == 'initialize':
        return {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                'serverInfo': {'name': 'ha-restricted-worker', 'version': '0.3.0'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': TOOLS}
    if method == 'tools/call':
        name = params.get('name')
        args = params.get('arguments', {})
        validate(name, args)
        payload = args if name == 'run' else {'action': name, 'args': args}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(100)
                connection.connect(SOCKET)
                connection.sendall(json.dumps(payload).encode()+b'\n')
                with connection.makefile('rb') as stream:
                    data = stream.readline(2*1024*1024)
                response = json.loads(data)
            return {'content': [{'type': 'text', 'text': json.dumps(response)}],
                    'isError': bool(response.get('error') or response.get('timedOut') or response.get('exitCode') not in (None, 0))}
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
