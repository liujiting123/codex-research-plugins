"""Exercise restart lifecycle with process boundaries mocked; never closes the app."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import relaunch
import runtime


class RelaunchTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin', 'macOS process detection')
    def test_host_detection_with_renamed_command_line(self):
        with subprocess.Popen(['skin-host-probe'], executable='/bin/cat',
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE) as probe:
            try:
                probe.stdin.write(b'ready\n')
                probe.stdin.flush()
                self.assertEqual(probe.stdout.readline(), b'ready\n')
                self.assertIn(probe.pid, relaunch.host_pids(Path('/bin/cat')))
            finally:
                probe.communicate(timeout=5)

    def pending_job(self, directory):
        job = {'id': 'a' * 32, 'pid': os.getpid(), 'createdAt': relaunch.now(),
               'phase': 'restarting', 'stage': 'scheduled',
               'status': {'phase': 'restarting', 'applied': False, 'connected': False, 'message': 'starting'}}
        relaunch.write_job(directory, job)
        return job

    def test_scheduler_detaches_and_duplicate_click_does_not_spawn_twice(self):
        with tempfile.TemporaryDirectory() as directory, patch('relaunch.host_executable'), \
             patch('relaunch.subprocess.Popen', return_value=SimpleNamespace(pid=os.getpid())) as spawn:
            first = relaunch.schedule(directory)
            second = relaunch.schedule(directory)
            self.assertEqual(first, second)
            spawn.assert_called_once()
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            self.assertEqual(relaunch.read_job(directory)['pid'], os.getpid())
            self.assertFalse(first['applied'])

    def test_spawn_failure_preserves_preferences_and_reports_failure(self):
        waiting = {'phase': 'waiting', 'connected': False, 'applied': False}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'CODEX_SKIN_STATE_DIR': directory}), \
             patch('runtime.run_engine', return_value=waiting), patch('runtime.start_watcher'), \
             patch('runtime.persist_theme', return_value={'saved': True}), \
             patch('relaunch.host_executable'), patch('relaunch.subprocess.Popen', side_effect=OSError('failed')):
            status = runtime.apply_skin('dsh:nebula', {'accent': '#123456'}, restart_when_needed=True)
            self.assertEqual(status['phase'], 'error')
            self.assertFalse(status['applied'])
            self.assertEqual(runtime.current_preferences()['overrides']['accent'], '#123456')
            self.assertEqual(runtime.runtime_status()['phase'], 'error')

    def test_cancel_before_helper_quits_does_not_touch_the_app(self):
        with tempfile.TemporaryDirectory() as directory, patch('relaunch.time.sleep'), \
             patch('relaunch.subprocess.run') as command:
            job = self.pending_job(directory)
            relaunch.cancel_before_quit(directory)
            relaunch.execute(directory, job['id'])
            command.assert_not_called()

    def test_cancelled_graceful_quit_does_not_launch_another_instance(self):
        with tempfile.TemporaryDirectory() as directory, patch('relaunch.time.sleep'), \
             patch('relaunch.host_executable', return_value=Path('/Applications/ChatGPT.app/Contents/MacOS/ChatGPT')), \
             patch('relaunch.host_pids', return_value={123}), \
             patch('relaunch.subprocess.run', return_value=SimpleNamespace(returncode=1, stderr='cancelled')) as command:
            job = self.pending_job(directory)
            relaunch.execute(directory, job['id'])
            command.assert_called_once()
            self.assertEqual(command.call_args.args[0][0], '/usr/bin/osascript')
            self.assertEqual(relaunch.read_job(directory)['phase'], 'error')

    def test_quit_timeout_never_force_kills_or_opens_another_instance(self):
        with tempfile.TemporaryDirectory() as directory, patch('relaunch.time.sleep'), \
             patch('relaunch.time.monotonic', side_effect=[0, 31]), \
             patch('relaunch.host_executable', return_value=Path('/Applications/ChatGPT.app/Contents/MacOS/ChatGPT')), \
             patch('relaunch.host_pids', return_value={123}), \
             patch('relaunch.subprocess.run', return_value=SimpleNamespace(returncode=0)) as command:
            job = self.pending_job(directory)
            relaunch.execute(directory, job['id'])
            command.assert_called_once()
            result = relaunch.read_job(directory)
            self.assertEqual(result['phase'], 'error')
            self.assertIn('未强制关闭', result['status']['message'])

    def test_reopen_then_applies_and_only_reports_confirmed_result(self):
        applied = {'phase': 'applied', 'connected': True, 'applied': True, 'themeId': 'dsh:nebula', 'message': 'applied'}
        with tempfile.TemporaryDirectory() as directory, patch('relaunch.time.sleep'), \
             patch('relaunch.host_executable', return_value=Path('/Applications/ChatGPT.app/Contents/MacOS/ChatGPT')), \
             patch('relaunch.host_pids', side_effect=[{123}, set()]), \
             patch('relaunch.subprocess.run', return_value=SimpleNamespace(returncode=0)) as command, \
             patch('runtime.run_engine', return_value=applied) as engine:
            job = self.pending_job(directory)
            relaunch.execute(directory, job['id'])
            self.assertEqual(command.call_count, 2)
            self.assertEqual(command.call_args.args[0][0], '/usr/bin/open')
            self.assertIn('--remote-debugging-address=127.0.0.1', command.call_args.args[0])
            engine.assert_called_once_with('apply')
            result = relaunch.read_job(directory)
            self.assertEqual(result['phase'], 'complete')
            self.assertTrue(result['status']['applied'])

    def test_open_request_without_applied_result_stays_unconfirmed(self):
        waiting = {'phase': 'waiting', 'connected': False, 'applied': False}
        with tempfile.TemporaryDirectory() as directory, patch('relaunch.time.sleep'), \
             patch('relaunch.time.monotonic', side_effect=[0, 0, 1, 46]), \
             patch('relaunch.host_executable', return_value=Path('/Applications/ChatGPT.app/Contents/MacOS/ChatGPT')), \
             patch('relaunch.host_pids', side_effect=[{123}, set()]), \
             patch('relaunch.subprocess.run', return_value=SimpleNamespace(returncode=0)), \
             patch('runtime.run_engine', return_value=waiting):
            job = self.pending_job(directory)
            relaunch.execute(directory, job['id'])
            result = relaunch.read_job(directory)
            self.assertEqual(result['phase'], 'error')
            self.assertFalse(result['status']['applied'])
            self.assertIn('尚未确认', result['status']['message'])

    def test_runtime_shows_restart_instead_of_stale_applied_status(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'CODEX_SKIN_STATE_DIR': directory}):
            runtime.atomic_json(Path(directory) / 'runtime-status.json',
                                {'phase': 'applied', 'applied': True, 'connected': True, 'checkedAt': relaunch.now()})
            self.pending_job(directory)
            self.assertEqual(runtime.runtime_status()['phase'], 'restarting')
            self.assertFalse(runtime.runtime_status()['applied'])


if __name__ == '__main__':
    unittest.main()
