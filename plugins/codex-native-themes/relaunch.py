"""A user-triggered, detached graceful restart; never force-kills Codex."""
import argparse
import ctypes
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time
import uuid
from host_environment import app_bundle, BUNDLE_ID

PORT = 9341


def now():
    return datetime.now(timezone.utc).isoformat()


def read_job(directory):
    try:
        value = json.loads((Path(directory) / 'restart.json').read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_job(directory, job):
    from runtime import atomic_json
    atomic_json(Path(directory) / 'restart.json', job)


def process_alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def restart_status(directory):
    job = read_job(directory)
    if job.get('phase') == 'error':
        return job.get('status')
    if job.get('phase') != 'restarting':
        return None
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(job['createdAt'])).total_seconds()
    except (KeyError, TypeError, ValueError):
        age = 121
    if age > 120 or not process_alive(job.get('pid')):
        return {'phase': 'error', 'connected': False, 'applied': False,
                'message': '上次自动重启未完成，设置已保存，请点击按钮重试。'}
    return job.get('status')


def dismiss_result(directory):
    job = read_job(directory)
    if job.get('phase') in {'error', 'complete'}:
        write_job(directory, {**job, 'phase': 'dismissed'})


def cancel_before_quit(directory):
    job = read_job(directory)
    if job.get('phase') == 'restarting' and job.get('stage') == 'scheduled':
        write_job(directory, {**job, 'phase': 'cancelled'})


def host_executable():
    if sys.platform != 'darwin':
        raise ValueError('当前自动重启仅支持 macOS。')
    app = app_bundle()
    if app is None:
        raise ValueError('未找到已安装的 Codex 应用；可通过 CODEX_DESKTOP_APP 指定 .app 路径。')
    try:
        with (app / 'Contents/Info.plist').open('rb') as handle:
            info = plistlib.load(handle)
        executable = app / 'Contents/MacOS' / info['CFBundleExecutable']
        if info.get('CFBundleIdentifier') != BUNDLE_ID or not executable.is_file():
            raise ValueError('未找到匹配的 Codex 应用。')
        return executable
    except (OSError, KeyError, plistlib.InvalidFileException):
        raise ValueError('未找到已安装的 Codex 应用。') from None


def schedule(directory):
    """Return a scheduled status only after the detached helper was created."""
    from runtime import atomic_json
    host_executable()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.restart.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = restart_status(directory)
        if previous and previous.get('phase') == 'restarting':
            return previous
        status = {'phase': 'restarting', 'connected': False, 'applied': False,
                  'port': PORT, 'checkedAt': now(),
                  'message': '设置已保存，正在自动重启 Codex…'}
        job = {'id': uuid.uuid4().hex, 'phase': 'restarting', 'stage': 'scheduled',
               'createdAt': now(), 'status': status}
        write_job(directory, job)
        try:
            helper = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), '--state-dir', str(directory), '--job-id', job['id']],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, close_fds=True)
            job['pid'] = helper.pid
        except OSError:
            status = {**status, 'phase': 'error',
                      'message': '自动重启未能启动，设置已保存，请重试。'}
            job.update(phase='error', status=status)
        write_job(directory, job)
        atomic_json(directory / 'runtime-status.json', status)
        return status


def host_pids(executable):
    # Match the actual executable: Electron can rename its command line.
    try:
        proc = ctypes.CDLL('/usr/lib/libproc.dylib')
    except OSError:
        raise ValueError('无法确认 Codex 是否已正常退出。') from None
    proc.proc_listallpids.argtypes = (ctypes.c_void_p, ctypes.c_int)
    proc.proc_listallpids.restype = ctypes.c_int
    proc.proc_pidpath.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
    proc.proc_pidpath.restype = ctypes.c_int
    capacity = proc.proc_listallpids(None, 0)
    if capacity <= 0:
        raise ValueError('无法确认 Codex 是否已正常退出。')
    processes = (ctypes.c_int * (capacity + 64))()
    count = proc.proc_listallpids(processes, ctypes.sizeof(processes))
    if count <= 0:
        raise ValueError('无法确认 Codex 是否已正常退出。')
    expected = os.fsencode(Path(executable).resolve())
    buffer = ctypes.create_string_buffer(4096)
    return {pid for pid in processes[:count]
            if pid > 0 and proc.proc_pidpath(pid, buffer, len(buffer)) > 0
            and buffer.value == expected}


def update(directory, job_id, stage, status, phase='restarting'):
    from runtime import atomic_json
    job = read_job(directory)
    if job.get('id') != job_id:
        return
    job.update(stage=stage, phase=phase, status={**status, 'checkedAt': now()})
    write_job(directory, job)
    atomic_json(Path(directory) / 'runtime-status.json', job['status'])


def execute(directory, job_id):
    """Called only by the helper created after an explicit button click."""
    from runtime import run_engine
    # Let the host render the response before its own process exits.
    time.sleep(2)
    job = read_job(directory)
    if job.get('id') != job_id or job.get('phase') != 'restarting':
        return
    status = job['status']
    stage = 'quitting'
    try:
        executable = host_executable()
        update(directory, job_id, stage, {**status, 'message': '正在正常退出 Codex…'})
        if host_pids(executable):
            result = subprocess.run(
                ['/usr/bin/osascript', '-e', 'tell application id "com.openai.codex" to quit'],
                capture_output=True, text=True, timeout=20)
            if result.returncode != 0:
                if '-1743' in (result.stderr or ''):
                    raise ValueError('macOS 未允许正常退出 Codex，自动重启被阻止；允许系统的自动化请求后可重试，设置已保存。')
                raise ValueError('Codex 的正常退出被取消或未完成，设置已保存，请重试。')
        deadline = time.monotonic() + 30
        while host_pids(executable):
            if time.monotonic() >= deadline:
                raise ValueError('Codex 尚未正常退出，未强制关闭；设置已保存，请重试。')
            time.sleep(.25)
        stage = 'opening'
        update(directory, job_id, stage, {**status, 'message': '正在重新打开 Codex…'})
        result = subprocess.run(
            ['/usr/bin/open', str(executable.parents[2]), '--args', '--remote-debugging-port=9341', '--remote-debugging-address=127.0.0.1'],
            capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            raise ValueError('Codex 已退出，但重新打开失败，设置仍保留。')
        stage = 'applying'
        update(directory, job_id, stage, {**status, 'message': 'Codex 正在打开，随后会自动应用所选效果…'})
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            status = run_engine('apply')
            if status.get('phase') in {'applied', 'paused'}:
                update(directory, job_id, 'done', status, phase='complete')
                return
            time.sleep(1)
        update(directory, job_id, 'applying', {**status, 'phase': 'error',
               'message': '已发送重新打开请求，但尚未确认所选效果生效。请在面板重试应用。'}, phase='error')
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        message = str(error) if isinstance(error, ValueError) else '自动重启未完成，设置已保留，请重试。'
        update(directory, job_id, stage, {'phase': 'error', 'connected': False, 'applied': False,
               'port': PORT, 'message': message}, phase='error')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--job-id', required=True)
    arguments = parser.parse_args()
    if re.fullmatch(r'[0-9a-f]{32}', arguments.job_id):
        execute(arguments.state_dir, arguments.job_id)
