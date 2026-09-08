import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('install_flow', Path(__file__).resolve().parents[1] / 'scripts/install.py')
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)


class InstallFlowTests(unittest.TestCase):
    def invoke(self, args, result, tty=False, answer='install'):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(flow.mark, 'verify_package'), \
             patch.object(flow.platform, 'system', return_value='Darwin'), \
             patch.object(flow.platform, 'machine', return_value='arm64'), \
             patch.object(flow.subprocess, 'run'), \
             patch.object(flow.mark, 'source_app', return_value=Path('/Applications/ChatGPT.app')), \
             patch.object(flow.updater, 'check', return_value=result), \
             patch.object(flow.updater, 'schedule', return_value={'result_file':temp+'/result.json','log':temp+'/log'}) as schedule, \
             patch.object(flow.sys.stdin, 'isatty', return_value=tty), \
             patch('builtins.input', return_value=answer), \
             patch.object(flow.sys, 'argv', ['install.py','--state-dir',temp,*args]), \
             contextlib.redirect_stdout(io.StringIO()):
            code = flow.main()
            return code, schedule.call_count

    def test_check_never_schedules_even_with_yes(self):
        self.assertEqual(self.invoke(['--check','--yes'], {'status':'available','version':'0.1.0-preview.12','ticket':'t'}),(0,0))

    def test_failed_checks_and_current_version_never_install(self):
        for status, code in [('offline',3),('no_compatible_release',2),('up_to_date',0)]:
            self.assertEqual(self.invoke(['--yes'], {'status':status}),(code,0))

    def test_noninteractive_requires_explicit_yes(self):
        self.assertEqual(self.invoke([], {'status':'available','version':'v','ticket':'t'}),(2,0))

    def test_interactive_cancel_never_installs(self):
        self.assertEqual(self.invoke([], {'status':'available','version':'v','ticket':'t'},tty=True,answer='cancel'),(0,0))

    def test_confirmed_install_schedules_once(self):
        self.assertEqual(self.invoke(['--yes','--no-wait'], {'status':'available','version':'v','ticket':'t'}),(0,1))

    def test_result_not_job_status_is_authoritative(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            state=Path(temp);result=state/'result.json';job={'result_file':str(result),'log':str(state/'log')}
            flow.mark.atomic_json(state/'update-job.json',{'status':'complete','result_file':str(state/'different.json')})
            self.assertEqual(flow.wait_for_result(state,job,timeout=0.001,interval=0),4)
            flow.mark.atomic_json(result,{'status':'error','message':'failed'})
            self.assertEqual(flow.wait_for_result(state,job),1)
            flow.mark.atomic_json(result,{'status':'complete'})
            self.assertEqual(flow.wait_for_result(state,job),0)


if __name__ == '__main__':
    unittest.main()
