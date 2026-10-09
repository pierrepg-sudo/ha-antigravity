import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_mobile import m
import command_worker as worker
import worker_mcp as mcp


class WorkerTests(unittest.TestCase):
    def test_invalid_commands_never_spawn(self):
        with patch.object(worker.subprocess,'Popen') as spawn:
            for command in ('', ' ', None, 'a'*32769, 'a\x00b'):
                with self.assertRaises(ValueError):worker.execute(command,'label')
            spawn.assert_not_called()

    def test_adapter_never_executes_and_unavailable_is_error(self):
        self.assertEqual(mcp.dispatch({'method':'tools/list'})['tools'][0]['name'],'run')
        self.assertIn('tools',mcp.dispatch({'method':'initialize'})['capabilities'])
        with patch.object(mcp.socket,'socket',side_effect=OSError):
            result=mcp.dispatch({'method':'tools/call','params':{'name':'run','arguments':{'command':'true'}}})
            self.assertTrue(result['isError'])
        for args in ({'command':'true','cwd':'/tmp'}, {'command':None}, {'command':'a\x00b'}):
            with self.assertRaises(ValueError):mcp.dispatch({'method':'tools/call','params':{'name':'run','arguments':args}})

    def test_broker_output_and_timeout_cleanup(self):
        real_spawn=subprocess.Popen
        # A test-only stand-in for aa-exec lets us verify broker pipe/timeout logic
        # without claiming AppArmor enforcement in this development environment.
        def spawn(argv, **kwargs):
            self.assertEqual(argv[:4],['/usr/bin/python3','-I','/usr/local/bin/network_job.py','outer//command_worker'])
            self.assertTrue(kwargs['close_fds'])
            self.assertEqual(set(kwargs['env']),{'PATH','LANG'})
            return real_spawn(['/bin/bash','-c',argv[-1]],**kwargs)
        with tempfile.TemporaryDirectory() as d, patch.object(worker,'TMP',Path(d)), patch.object(worker.subprocess,'Popen',side_effect=spawn):
            result=worker.execute("python3 -c 'print(\"x\"*300000)'",'outer//command_worker')
            self.assertTrue(result['truncated'])
            self.assertEqual(len(result['output']),worker.MAX_OUTPUT)
            self.assertEqual(list(Path(d).iterdir()),[])
            result=worker.execute('sleep 10','outer//command_worker',timeout=0.1)
            self.assertTrue(result['timedOut'])
            self.assertEqual(list(Path(d).iterdir()),[])

    def test_real_syscall_filter_allows_ip_but_denies_escape(self):
        source=Path(__file__).parents[1]/'antigravity/restricted_exec.c'
        with tempfile.TemporaryDirectory() as d:
            harness=Path(d)/'filter.c'
            # Reuse the actual filter in a disposable test executable; no test
            # switch or bypass is compiled into the shipped worker.
            harness.write_text('#define main worker_entry\n#include '+json.dumps(str(source))+'\n#undef main\n'
                '#include <sys/socket.h>\n#include <pthread.h>\n'
                'static void *send_byte(void *p){int fd=*(int*)p;return (void*)(long)(write(fd,"x",1)!=1); }\n'
                'int main(void) {\n'
                'if(prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)){return 2;} install_filter();\n'
                'int s=socket(AF_INET,SOCK_STREAM,0);if(s<0)return 3;close(s);\n'
                'if(socket(AF_UNIX,SOCK_STREAM,0)!=-1 || errno!=EPERM)return 4;\n'
                'if(socket(AF_NETLINK,SOCK_RAW,0)!=-1 || errno!=EPERM)return 8;\n'
                'if(socket(AF_INET,SOCK_RAW,0)!=-1 || errno!=EPERM)return 9;\n'
                's=socket(AF_INET6,SOCK_DGRAM|SOCK_CLOEXEC,0);if(s<0)return 10;close(s);\n'
                'int pair[2];char b;void *result;pthread_t thread;\n'
                'if(socketpair(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0,pair))return 11;\n'
                'if(pthread_create(&thread,0,send_byte,&pair[1]))return 12;\n'
                'if(pthread_join(thread,&result)||result||read(pair[0],&b,1)!=1||b!="x"[0])return 13;\n'
                'close(pair[0]);close(pair[1]);\n'
                'if(socketpair(AF_UNIX,SOCK_DGRAM,0,pair)!=-1||errno!=EPERM)return 14;\n'
                'if(socketpair(AF_INET,SOCK_STREAM,0,pair)!=-1||errno!=EPERM)return 15;\n'
                'if(socketpair(AF_UNIX,SOCK_STREAM,1,pair)!=-1||errno!=EPERM)return 16;\n'
                'if(setsid()!=-1 || errno!=EPERM)return 5;\n'
                'if(setpgid(0,0)!=-1 || errno!=EPERM)return 6;\n'
                'execl("/usr/bin/true","true",(char*)0);return 7; }\n')
            binary=Path(d)/'filter'
            build=subprocess.run(['cc','-pthread','-O2','-Wall','-Wextra','-Werror',str(harness),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            self.assertEqual(subprocess.run([str(binary)],timeout=5).returncode,0)
