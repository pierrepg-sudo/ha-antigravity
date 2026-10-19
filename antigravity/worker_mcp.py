"""MCP stdio adapter: pass commands to the separate-UID broker, never execute here."""
import json
import re
import socket
import sys
import os
import shlex


def project_output():
    path = os.environ.get('HA_PROJECT_OUTPUT', '/data/workspace/outputs')
    suffix = path.removeprefix('/data/workspace/outputs/')
    if path == '/data/workspace/outputs':
        return path
    if not path.startswith('/data/workspace/outputs/') or '/' in suffix or '\\' in suffix or suffix in ('', '.', '..') or any(ord(c) < 32 for c in suffix):
        raise ValueError('Invalid project output directory')
    return path

SOCKET = '/run/antigravity-worker/worker.sock'
TOOL = {'name': 'run',
        'description': 'Run local C/C++ builds, Python, Pandoc/PDF generation and file processing in the restricted worker. Working directory: /data/workspace/outputs. Read originals from /data/inputs. Public outbound TCP/UDP internet is allowed. Private/local networks, inbound listeners, CLI credentials, private CLI files and interactive sessions and self-detaching daemons are blocked. Use start for managed foreground jobs that need more than 90 seconds. Maximum 90 seconds, 256 KiB output, 32 MiB per file. Use this instead of the blocked native terminal tool.',
        'inputSchema': {'type': 'object', 'properties': {'command': {'type': 'string', 'maxLength': 32768}},
                        'required': ['command'], 'additionalProperties': False}}


def job_tool(name, description, properties, required):
    return {'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'properties': properties,
                            'required': required, 'additionalProperties': False}}

JOB_ID = {'job_id': {'type': 'string', 'pattern': '^[0-9a-f]{32}$',
    'description': 'Full 32-character id from start or status. Argument key is job_id, not id or name. Call status with {} to recover it; never abbreviate.'}}
RESTART = {'resume_after_restart': {'type': 'boolean', 'default': False,
    'description': 'Opt-in only with user authorization. Restart after add-on/HAOS interruption, never after normal completion, failure or explicit stop. Script must safely reload its own state.'}}
TOOLS = [TOOL,
    job_tool('start', 'Start a managed long-running FOREGROUND command in the restricted worker. Same public-internet-only and filesystem protections as run. At most two managed jobs. Return immediately with a job ID; use status/logs to verify startup. Do not use nohup, setsid, daemon mode, PID-file launchers or shell backgrounding. Restart recovery is off by default; set resume_after_restart only with user authorization. Commands restart from the beginning, not from in-memory state. Never put credentials inline in a restartable command; load them from existing configuration. stdout/stderr logs are bounded; keep secrets out of output.',
             {'command': {'type': 'string', 'maxLength': 32768},
              'name': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'}, **RESTART}, ['command', 'name']),
    job_tool('restart_policy', 'Enable or disable restart recovery for an existing job without restarting it. Explicit user authorization is required to enable. Enabling requires an active job. Disabling clears persisted restart intent. Inspect status first; use full job_id.', {**JOB_ID, **RESTART}, ['job_id', 'resume_after_restart']),
    job_tool('status', 'List managed jobs or inspect one. Running means the process is active, not that the application is healthy. Does not use arbitrary PIDs.', JOB_ID, []),
    job_tool('stop', 'Stop an owned managed job and its descendants, with a short termination grace period. Returns stopping; check status for completion.', JOB_ID, ['job_id']),
    job_tool('logs', 'Read the bounded stdout/stderr tail of an owned job. Logs may contain application secrets; redact them before displaying. Files redirected by the script are not included.', JOB_ID, ['job_id'])]


RECOVERY_GUIDANCE = (
    'For every current or future script/agent launch failure, inspect the cause. '
    'If blocked native execution, a self-detaching launcher (nohup/setsid/backgrounding), '
    'or the 90-second run limit is the cause, always propose the existing worker: '
    'run for bounded work, or a managed foreground job via start for long-running work. '
    'Do not create another worker or service. A timeout alone does not prove continuous execution. '
    'Call status with {} first; inspect existing jobs and logs to avoid duplicates. '
    'Inspect the launcher and propose a foreground adaptation preserving .env loading, '
    'dependency paths and attached stdout/stderr without exposing secrets. '
    'Proceed with adaptation/start when already authorized by the user; otherwise ask before starting. '
    'Check for partial work or external actions before retrying; never automatically replay a failed command. '
    'After start, verify status and logs using the full returned id as job_id. '
    'Missing dependencies, invalid credentials, application bugs, resource limits and private-network '
    'denials need their own fixes; a managed job does not resolve them. '
    'If the worker itself denies execution, is unavailable or fails isolation checks, stop and report it. '
    'Keep security settings and additional user restrictions unchanged.'
)

INSTRUCTIONS = (
    'ha-restricted-worker is the configured execution method for user-requested local work. '
    'Native command/unsandboxed tools remain denied; this worker is not a bypass. '
    'Use run for short commands and start for long-running foreground scripts. '
    'Restart recovery is off by default. Only enable resume_after_restart on start or restart_policy when the user authorizes restart after interruption. '
    'A request to start once is not restart authorization. Before opting in, inspect whether the script safely reloads its state and avoids duplicate external actions. '
    'Never place secrets inline in a restartable command; load existing configuration. Use restart_policy to change an active job without restarting it. '
    'Recovery occurs only after isolation checks pass, with at most three attempts in ten minutes. Normal completion, failure and explicit stop clear restart intent. '
    'CLI-only restarts leave worker jobs running; add-on/HAOS restarts launch authorized jobs again from the beginning. '
    'Before starting, call status with {} to avoid duplicates. '
    'For logs/stop/status of one job, pass {"job_id":"<full id from status>"}. '
    'Never use id, name, PID or an abbreviated ID as the argument. '
    'On argument errors, correct the call without restarting the job. '
    'Tool schemas are available in tools/list and /opt/antigravity-workspace/WORKER_TOOLS.json; '
    'do not read private CLI tool-cache files. Respect any additional user ask/deny rules. '
    'If worker execution is denied or unavailable, report it without using another execution path. '
    + RECOVERY_GUIDANCE
)


def add_recovery_guidance(name, response):
    """Annotate results only; never infer authorization or execute a retry."""
    result = dict(response)
    if response.get('error'):
        result['guidance'] = (
            'Report the worker error. Do not launch another job to work around it. '
            'For duplicate/capacity or job-ID errors, call status with {} and inspect existing jobs; '
            'do not stop them without authorization. For denial/isolation failures, stop and report. '
            'No native terminal fallback or security changes.')
    elif name == 'run' and response.get('timedOut'):
        result['guidance'] = (
            'The short-command time limit was reached and its process group was cleaned up. '
            'Work or external actions completed before timeout may still have taken effect. '
            + RECOVERY_GUIDANCE)
    elif name in ('run', 'start', 'status', 'logs') and response.get('exitCode') not in (None, 0):
        result['guidance'] = (
            'Execution failed; the exit code alone does not identify the cause. '
            + RECOVERY_GUIDANCE)
    return result


def export_docs(directory):
    """Build-time export from the live schemas; never copy the private CLI cache."""
    from pathlib import Path
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    (root / 'WORKER_TOOLS.json').write_text(json.dumps({'instructions': INSTRUCTIONS, 'tools': TOOLS}, indent=2) + '\n')
    guide = root / 'AGENTS.md'
    guide.write_text(guide.read_text() + '\n## Exact worker tool contract\n\n' + INSTRUCTIONS +
                     '\n\n```json\n' + json.dumps(TOOLS, indent=2) + '\n```\n')


def validate(name, args):
    if not isinstance(args, dict):
        raise ValueError('Expected arguments')
    if name in ('run', 'start'):
        required = {'command'} if name == 'run' else {'command', 'name'}
        allowed = required if name == 'run' else required | {'resume_after_restart'}
        if not required <= set(args) or set(args) - allowed:
            raise ValueError('Invalid command arguments')
        command = args['command']
        if not isinstance(command, str) or not command.strip() or len(command.encode()) > 32768 or '\x00' in command:
            raise ValueError('Invalid command')
        if name == 'start':
            if type(args.get('resume_after_restart', False)) is not bool:
                raise ValueError('resume_after_restart must be boolean')
            if not isinstance(args['name'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args['name']):
                raise ValueError('Invalid job name')
    elif name in ('stop', 'status', 'logs', 'restart_policy'):
        if name == 'status' and not args:
            return
        expected = {'job_id', 'resume_after_restart'} if name == 'restart_policy' else {'job_id'}
        if name == 'restart_policy' and type(args.get('resume_after_restart')) is not bool:
            raise ValueError('restart_policy requires job_id and boolean resume_after_restart')
        if set(args) != expected or not isinstance(args['job_id'], str) or not re.fullmatch(r'[0-9a-f]{32}', args['job_id']):
            raise ValueError('Expected {"job_id": "<full 32-character id>"}. Call status with {} to find it. Do not restart the job or use id/name/PID.')
    else:
        raise ValueError('Unknown tool')


def dispatch(request):
    method = request.get('method')
    params = request.get('params', {})
    if method == 'initialize':
        return {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                'serverInfo': {'name': 'ha-restricted-worker', 'version': '0.10.28'},
                'instructions': INSTRUCTIONS + '\nThis session saves generated files by default in ' + project_output() + '. Use this absolute directory for native file writes. Worker commands start there; it is not a trusted configuration workspace.'}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': TOOLS}
    if method == 'tools/call':
        name = params.get('name')
        args = params.get('arguments', {})
        try:
            validate(name, args)
        except ValueError as error:
            tool = next((t for t in TOOLS if t['name'] == name), None)
            detail = {'error': str(error), 'requestSent': False,
                      'guidance': 'No job was changed. Correct the arguments; never use native terminal fallback.'}
            if tool:
                detail['inputSchema'] = tool['inputSchema']
            return {'content': [{'type': 'text', 'text': json.dumps(detail)}], 'isError': True}
        if name in ('run', 'start') and project_output() != '/data/workspace/outputs':
            args = dict(args, command='cd -- ' + shlex.quote(project_output()) + ' && ' + args['command'])
        payload = args if name == 'run' else {'action': name, 'args': args}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(100)
                connection.connect(SOCKET)
                connection.sendall(json.dumps(payload).encode()+b'\n')
                with connection.makefile('rb') as stream:
                    data = stream.readline(2*1024*1024)
                response = json.loads(data)
            response = add_recovery_guidance(name, response)
            return {'content': [{'type': 'text', 'text': json.dumps(response)}],
                    'isError': bool(response.get('error') or response.get('timedOut') or response.get('exitCode') not in (None, 0))}
        except (OSError, ValueError):
            return {'content': [{'type': 'text', 'text': 'Restricted worker communication failed. Execution outcome may be unknown if the request was sent. Do not retry automatically. When available, call status with {} and inspect jobs/logs before any further start. Report the error; there is no native shell fallback.'}], 'isError': True}
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
    if len(sys.argv) == 3 and sys.argv[1] == '--export-docs':
        export_docs(sys.argv[2])
    else:
        main()
