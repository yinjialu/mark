#!/usr/bin/env python3
"""Version-pinned client installer with opt-in GitHub release updates."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'integration'))
from patch_client import Archive, digest, prepare

PUBLIC_KEYS = {
    'com.apple.security.app-sandbox', 'com.apple.security.automation.apple-events',
    'com.apple.security.cs.allow-jit', 'com.apple.security.cs.allow-unsigned-executable-memory',
    'com.apple.security.cs.disable-library-validation', 'com.apple.security.device.audio-input',
    'com.apple.security.device.camera', 'com.apple.security.files.user-selected.read-write',
    'com.apple.security.network.client', 'com.apple.security.personal-information.calendars',
}
EXCEPTION = 'com.apple.security.cs.disable-library-validation'


class MarkError(Exception):
    pass


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def read_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def prepare_state(state):
    """Create private runtime storage and keep its internal app copies out of Spotlight."""
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    (state / '.metadata_never_index').touch(exist_ok=True)
    return state


def inventory(root=ROOT):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and p.name not in ('SHA256SUMS.json', '.DS_Store') and not p.name.startswith('._')
            and not {'.git', '__pycache__'}.intersection(p.relative_to(root).parts) and p.suffix != '.pyc'}


def verify_package(root=ROOT):
    expected = read_json(root / 'SHA256SUMS.json')
    if not expected or expected != inventory(root):
        raise MarkError('安装包校验失败，请重新解压完整的 mark 安装包。')
    # Integrity detects damage, not publisher identity; no unauthenticated download/update.
    return hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()[:16]


def source_app(explicit=None):
    if explicit:
        return Path(explicit).expanduser().resolve()
    for app in (Path('/Applications/ChatGPT.app'), Path.home() / 'Applications/ChatGPT.app',
                Path('/Applications/Codex.app'), Path.home() / 'Applications/Codex.app'):
        if app.exists():
            try:
                if plistlib.loads((app / 'Contents/Info.plist').read_bytes()).get('CFBundleIdentifier') == 'com.openai.codex':
                    return app.resolve()
            except (OSError, ValueError):
                pass
    raise MarkError('未找到正式 ChatGPT/Codex。请先安装，或通过 --app 指定应用路径。')


def select_adapter(info, header, architecture, adapters):
    return next((a for a in adapters if (a['bundle_id'], a['version'], a['build'], a['header_sha256'], a['architecture']) ==
                 (info.get('CFBundleIdentifier'), info.get('CFBundleShortVersionString'), str(info.get('CFBundleVersion')), header, architecture)), None)


def doctor(app):
    if platform.system() != 'Darwin':
        raise MarkError('原生界面集成目前只支持 macOS；标准插件可以单独使用。')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    header = digest(Archive(app / 'Contents/Resources/app.asar').raw_header)
    expected = info.get('ElectronAsarIntegrity', {}).get('Resources/app.asar', {}).get('hash')
    adapter = select_adapter(info, header, platform.machine(), read_json(ROOT / 'compatibility.json')['adapters']) if expected == header else None
    return {'status': 'supported' if adapter else 'unsupported_client', 'source_app': str(app),
            'version': info.get('CFBundleShortVersionString'), 'build': str(info.get('CFBundleVersion')),
            'architecture': platform.machine(), 'source_header_sha256': header, 'adapter': adapter,
            'message': '可自动生成适配副本' if adapter else '此版本尚未适配。请更新 mark 安装包；已有收藏和旧副本保留。'}


@contextmanager
def lock(state):
    state.mkdir(parents=True, exist_ok=True)
    with (state / '.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MarkError('另一个 mark 安装或切换正在进行，请稍候。')
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def entitlements(bundle):
    output = run(['/usr/bin/codesign', '-d', '--entitlements', '-', bundle], capture_output=True).stdout
    try:
        original = plistlib.loads(output)
        result = {k: v for k, v in original.items() if k in PUBLIC_KEYS and type(v) is bool}
    except (ValueError, plistlib.InvalidFileException):
        result = {k: v == 'true' for k, v in re.findall(r'\[Key\] ([^\n]+)\s+\[Value\]\s+\[Bool\] (true|false)', output.decode()) if k in PUBLIC_KEYS}
    if not result.get('com.apple.security.cs.allow-jit') or not result.get('com.apple.security.cs.allow-unsigned-executable-memory'):
        raise MarkError('客户端签名结构不符合适配器，已停止。')
    return result


def sign_copy(source, target, adapter, work):
    paths = [Path(adapter['helpers']) / ('Codex (' + name + ').app') for name in ('GPU', 'Service', 'Alerts', 'Renderer')] + [Path('.')]
    for index, relative in enumerate(paths):
        values = {**entitlements(source / relative), EXCEPTION: True}
        output = work / ('entitlements-' + str(index) + '.plist')
        output.write_bytes(plistlib.dumps(values))
        if relative == Path('.'):
            run(['/usr/bin/codesign', '--force', '--sign', '-', '--preserve-metadata=identifier,flags,runtime', '--timestamp=none', target / adapter['framework']])
        run(['/usr/bin/codesign', '--force', '--sign', '-', '--options', 'runtime', '--preserve-metadata=identifier,runtime',
             '--timestamp=none', '--entitlements', output, target / relative])
        if entitlements(target / relative) != values:
            raise MarkError('本地签名验证失败。')
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', target])


def verified(record):
    app = Path(record['app'])
    if not app.is_dir() or digest(Archive(app / 'Contents/Resources/app.asar').raw_header) != record['patched_header_sha256']:
        raise MarkError('测试副本已变化，请重新生成。')
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app], capture_output=True)
    probe = run([app / 'Contents/MacOS/ChatGPT', '--version'], capture_output=True, text=True, timeout=15)
    if probe.stdout.strip() != record['version']:
        raise MarkError('测试副本启动版本不匹配。')
    return app


def _managed_child(path, root):
    """Return the direct managed child containing path, or None when it is outside root."""
    try:
        relative = Path(path).expanduser().resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return root / relative.parts[0] if relative.parts else None


def _process_table():
    """Return process id, parent id and command without interpreting shell words."""
    try:
        completed = subprocess.run(['/bin/ps', '-A', '-o', 'pid=,ppid=,command='],
                                   check=False, capture_output=True, text=True)
    except OSError:
        return []
    if completed.returncode:
        return []
    rows = []
    for line in completed.stdout.splitlines():
        pieces = line.strip().split(None, 2)
        if len(pieces) != 3:
            continue
        try:
            rows.append((int(pieces[0]), int(pieces[1]), pieces[2]))
        except ValueError:
            pass
    return rows


def _app_root(command):
    marker = '.app/Contents/'
    end = command.find(marker)
    if not command.startswith('/') or end < 0:
        return None
    return Path(command[:end + 4])


def _is_helper(command, app):
    if not command.startswith(str(app) + '/Contents/'):
        return False
    return ('/browser_crashpad_handler ' in command or command.endswith('/browser_crashpad_handler')
            or '/bare-modifier-monitor ' in command or command.endswith('/bare-modifier-monitor'))


def terminate_app_helpers(app, rows=None):
    """Stop crash/keyboard helpers after their owning ChatGPT main process has exited."""
    app = Path(app)
    stopped = []
    for pid, _, command in rows if rows is not None else _process_table():
        if not _is_helper(command, app):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            stopped.append(pid)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
    return stopped


def prune_orphan_helpers(state):
    """Stop detached helpers for managed copies that no longer have a main process."""
    rows = _process_table()
    active = {_app_root(command) for _, _, command in rows
              if '/Contents/MacOS/ChatGPT' in command and _app_root(command)}
    builds = (Path(state) / 'builds').resolve()
    stopped = []
    seen = set()
    for _, parent, command in rows:
        app = _app_root(command)
        if parent != 1 or not app or app in active or app in seen or not _is_helper(command, app):
            continue
        try:
            app.resolve().relative_to(builds)
        except (OSError, ValueError):
            continue
        seen.add(app)
        stopped.extend(terminate_app_helpers(app, rows))
    return stopped


def prune_generations(state):
    """Remove unreferenced managed builds and packages after state has been committed."""
    state = Path(state)
    stopped = prune_orphan_helpers(state)
    data = read_json(state / 'state.json', {})
    builds = state / 'builds'
    packages = state / 'packages'
    keep_builds = set()
    keep_packages = set()
    for key in ('active', 'prepared', 'previous'):
        record = data.get(key)
        if not isinstance(record, dict):
            continue
        if record.get('app'):
            child = _managed_child(record['app'], builds)
            if child:
                keep_builds.add(child)
        package_id = record.get('package_id')
        if package_id and Path(str(package_id)).name == str(package_id):
            keep_packages.add(packages / str(package_id))
        if record.get('package'):
            child = _managed_child(record['package'], packages)
            if child:
                keep_packages.add(child)

    removed = {'builds': [], 'packages': [], 'processes': stopped, 'errors': []}
    for root, retained, marker, label in (
            (builds, keep_builds, ('build.json', 'failed.json'), 'builds'),
            (packages, keep_packages, ('SHA256SUMS.json',), 'packages')):
        if not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except OSError as error:
            removed['errors'].append(str(root) + ': ' + str(error))
            continue
        for child in children:
            if child in retained or child.is_symlink() or not child.is_dir():
                continue
            # Only delete directories created by mark; leave unexpected user content untouched.
            if not any((child / name).is_file() for name in marker):
                continue
            try:
                shutil.rmtree(child)
                removed[label].append(str(child))
            except OSError as error:
                removed['errors'].append(str(child) + ': ' + str(error))
    try:
        if removed['errors']:
            atomic_json(state / 'cleanup-warning.json', {'at': stamp(), 'errors': removed['errors'][:20]})
        else:
            (state / 'cleanup-warning.json').unlink(missing_ok=True)
    except OSError:
        pass  # Cleanup must never turn a healthy build or launch into a rollback.
    return removed


def prune_launcher_backups(state, keep=1):
    """Keep only the newest completed launcher rollback after a successful upgrade."""
    root = Path(state) / 'launcher-backups'
    if not root.is_dir():
        return []
    try:
        backups = sorted((path for path in root.iterdir() if path.is_dir() and not path.is_symlink()),
                         key=lambda path: path.stat().st_mtime_ns, reverse=True)
    except OSError:
        return []
    removed = []
    for path in backups[max(0, keep):]:
        try:
            shutil.rmtree(path)
            removed.append(str(path))
        except OSError:
            pass  # The next successful upgrade can retry old backup cleanup.
    return removed


def remember_build(state, record):
    # Committing a prepared build does not change the last successfully launched build.
    current = read_json(state / 'state.json', {})
    current.update(prepared=record, checked_at=stamp())
    atomic_json(state / 'state.json', current)
    prune_generations(state)


def build(app, state, accept=False):
    prepare_state(state)
    package_id = verify_package()
    check = doctor(app)
    atomic_json(state / 'compatibility-status.json', check)
    if check['status'] != 'supported':
        raise MarkError(check['message'] + ' 检测到版本：' + str(check['version']))
    consent = read_json(state / 'consent.json', {})
    if not accept and not consent.get('local_resign'):
        raise MarkError('首次安装需要明确接受测试副本的本地重签名。请运行 Install.command。')
    if accept:
        atomic_json(state / 'consent.json', {'local_resign': True, 'at': stamp(), 'scope': 'mark-generated test copies only'})
    settings = read_json(state / 'state.json', {})
    for prior in (settings.get('prepared'), settings.get('active')):
        if prior and prior.get('package_id') == package_id and prior.get('source_header_sha256') == check['source_header_sha256']:
            try:
                verified(prior)
                return prior
            except (OSError, subprocess.SubprocessError, MarkError):
                pass  # Preserve a changed copy for inspection; create a separate generation.
    run(['/usr/bin/xcode-select', '-p'], capture_output=True)
    run(['/usr/bin/python3', '--version'], capture_output=True)
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app], capture_output=True)
    identity = run(['/usr/bin/codesign', '-d', '--verbose=4', app], capture_output=True, text=True)
    if 'TeamIdentifier=2DC432GLL2' not in identity.stderr + identity.stdout:
        raise MarkError('源应用不具有适配器预期的 OpenAI 签名身份，已停止。')
    build_id = check['adapter']['id'] + '-' + package_id + '-' + uuid.uuid4().hex[:8]
    directory = state / 'builds' / build_id
    directory.mkdir(parents=True)
    target = directory / 'ChatGPT mark.app'
    try:
        report = prepare(app, directory / 'prepared', ROOT / 'plugins/codex-marks')
        run(['/bin/cp', '-cR', app, target])
        for relative in ('Contents/Info.plist', 'Contents/Resources/app.asar'):
            shutil.copy2(directory / 'prepared' / relative, target / relative)
        shutil.copytree(directory / 'prepared/Contents/Resources/codex-marks', target / 'Contents/Resources/codex-marks', dirs_exist_ok=True)
        icon = ROOT / 'assets/mark.icns'
        if not icon.is_file():
            raise MarkError('安装包缺少 mark 图标。')
        shutil.copy2(icon, target / 'Contents/Resources/mark.icns')
        info_path = target / 'Contents/Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info.pop('CFBundleIconName', None)
        info.update(CFBundleName='ChatGPT mark', CFBundleDisplayName='ChatGPT mark', CFBundleIconFile='mark.icns')
        info_path.write_bytes(plistlib.dumps(info))
        atomic_json(target / 'Contents/Resources/codex-marks/update-config.json', {
            'package': str(state / 'packages' / package_id), 'package_id': package_id,
            'state': str(state), 'source_app': str(app)})
        sign_copy(app, target, check['adapter'], directory)
        record = {'app': str(target), 'version': check['version'], 'source_build': check['build'],
                  'architecture': check['architecture'], 'bundle_id': check['adapter']['bundle_id'],
                  'source_app': str(app), 'source_header_sha256': check['source_header_sha256'],
                  'patched_header_sha256': report['patched_header_sha256'], 'package_id': package_id, 'mark_version': read_json(ROOT / 'compatibility.json')['release'], 'created_at': stamp(), 'adapter_id': check['adapter']['id']}
        verified(record)
        if doctor(app)['source_header_sha256'] != check['source_header_sha256']:
            raise MarkError('正式客户端在构建期间升级，请重新运行安装器。')
        remember_build(state, record)
        atomic_json(directory / 'build.json', record)
        return record
    except Exception:
        atomic_json(directory / 'failed.json', {'failed_at': stamp(), 'active_copy_unchanged': True})
        raise


def pids(app):
    executable = str(app / 'Contents/MacOS/ChatGPT')
    found = []
    for line in run(['/bin/ps', '-A', '-o', 'pid=,comm='], capture_output=True, text=True).stdout.splitlines():
        pieces = line.strip().split(None, 1)
        if len(pieces) == 2 and pieces[1] == executable:
            found.append(int(pieces[0]))
    return found


def active_codex():
    apps = []
    for line in run(['/bin/ps', '-A', '-o', 'pid=,comm='], capture_output=True, text=True).stdout.splitlines():
        pieces = line.strip().split(None, 1)
        if len(pieces) != 2 or not pieces[1].endswith('/Contents/MacOS/ChatGPT'):
            continue
        app = Path(pieces[1]).parents[2]
        try:
            if plistlib.loads((app / 'Contents/Info.plist').read_bytes()).get('CFBundleIdentifier') == 'com.openai.codex':
                apps.append(app)
        except (OSError, ValueError):
            pass
    return list(dict.fromkeys(apps))


def terminate(app):
    for pid in pids(app):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 20
    while pids(app) and time.monotonic() < deadline:
        time.sleep(.25)
    if pids(app):
        raise MarkError('当前客户端未退出，已停止切换；没有强制结束进程。')
    terminate_app_helpers(app)


def open_official(app):
    """Switch from a marked copy to the original signed app for its official updater."""
    app = app.resolve()
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != 'com.openai.codex':
        raise MarkError('正式客户端标识不匹配，已停止切换。')
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app], capture_output=True)
    identity = run(['/usr/bin/codesign', '-d', '--verbose=4', app], capture_output=True, text=True)
    if 'TeamIdentifier=2DC432GLL2' not in identity.stderr + identity.stdout:
        raise MarkError('目标不是预期的 OpenAI 签名客户端，已停止切换。')
    official_running = bool(pids(app))
    marked = [candidate for candidate in active_codex() if candidate != app]
    try:
        for candidate in marked:
            terminate(candidate)
        command = ['/usr/bin/open', '-a', app] if official_running else ['/usr/bin/open', '-n', '-a', app]
        run(command, capture_output=True, timeout=15)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if pids(app):
                return {'status': 'official_opened', 'app': str(app),
                        'message': '已打开正式 ChatGPT；请使用它的官方更新，完成后重新打开 mark。'}
            time.sleep(.25)
        raise MarkError('未检测到正式 ChatGPT 启动。')
    except Exception:
        if marked:
            run(['/usr/bin/open', '-n', '-a', marked[0]], capture_output=True)
        raise


def promote(state, record):
    data = read_json(state / 'state.json', {})
    if data.get('active') and data['active']['app'] != record['app']:
        data['previous'] = data['active']
    data.update(active=record, prepared=record, last_launch=stamp())
    atomic_json(state / 'state.json', data)
    try:
        from dock import sync_dock
        sync_dock(state, Path(record['app']))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # Dock preferences must never turn a healthy launch into a rollback.
        atomic_json(state / 'dock-warning.json', {'at': stamp(), 'message': str(error)[:1000]})
    prune_generations(state)


def launch_record(record, state, switch=False):
    target = verified(record)
    running = active_codex()
    if running == [target]:
        run(['/usr/bin/open', '-a', target])
        promote(state, record)
        return {'status': 'already_running', 'app': str(target)}
    others = [app for app in running if app != target]
    if others and not switch:
        raise MarkError('请先退出当前 Codex，或使用 Open mark.command 正常切换。')
    if len(others) > 1:
        raise MarkError('检测到多个 Codex 主窗口进程，请先手动退出多余副本。')
    fallback = others[0] if others else None
    if fallback:
        terminate(fallback)
    try:
        run(['/usr/bin/open', '-n', '-a', target], capture_output=True, timeout=15)
        deadline = time.monotonic() + 35
        started = None
        while time.monotonic() < deadline:
            if pids(target):
                started = started or time.monotonic()
                if time.monotonic() - started >= 20:
                    promote(state, record)
                    return {'status': 'running', 'app': str(target), 'native_ui_acceptance': 'pending'}
            elif started:
                raise MarkError('新副本启动后退出。')
            time.sleep(.5)
        raise MarkError('未检测到稳定运行的新副本。')
    except Exception as error:
        if pids(target):
            terminate(target)
        if fallback:
            run(['/usr/bin/open', '-n', '-a', fallback], capture_output=True)
        atomic_json(state / 'last-launch-error.json', {'at': stamp(), 'message': str(error)[:1000], 'fallback': str(fallback) if fallback else None})
        raise


def start_managed(app, state, accept=False):
    """Open the newest usable copy without letting an unsupported official update block launch."""
    active = read_json(state / 'state.json', {}).get('active')
    source_status = None
    try:
        source_status = doctor(app)
        atomic_json(state / 'compatibility-status.json', source_status)
        if source_status['status'] == 'supported':
            record = build(app, state, accept)
            result = launch_record(record, state, switch=True)
            atomic_json(state / 'startup-status.json', {
                'status': 'current', 'at': stamp(), 'app': record['app'],
                'source_version': source_status['version'], 'source_build': source_status['build']})
            return result
        reason = source_status['message']
        status = 'waiting_for_adapter'
    except (MarkError, OSError, ValueError, subprocess.SubprocessError) as error:
        reason = str(error)[:1000]
        status = 'rebuild_failed'
    if not active:
        raise MarkError(reason)
    result = launch_record(active, state, switch=True)
    message = ('正式版已升级，适配尚未发布；已继续打开当前 ChatGPT mark。'
               if status == 'waiting_for_adapter' else '新版副本准备失败；已继续打开上一可用版本。')
    atomic_json(state / 'startup-status.json', {
        'status': status, 'at': stamp(), 'app': active['app'], 'message': message,
        'reason': reason, 'source_version': source_status.get('version') if source_status else None,
        'source_build': source_status.get('build') if source_status else None})
    return {**result, 'compatibility_status': status, 'message': message}


def schedule_switch(app, state, command, switch=False, accept=False):
    """Return before Codex exits; the detached child owns switching and its result."""
    state.mkdir(parents=True, exist_ok=True)
    log = state / ('switch-' + uuid.uuid4().hex + '.log')
    result_path = log.with_suffix('.json')
    args = [sys.executable, '-B', str(ROOT / 'mark.py'), '--app', str(app),
            '--state-dir', str(state), command, '--deferred-result', str(result_path)]
    if switch:
        args.append('--switch')
    if accept:
        args.append('--accept-local-resign')
    with log.open('x') as output:
        log.chmod(0o600)
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    message = ('即将退出 ChatGPT mark 并打开正式 ChatGPT；请在正式版中完成官方更新。'
               if command == 'open-official' else '切换已安排；这不是启动成功。请检查 result_file 的最终状态。')
    return {'status': 'switch_scheduled', 'pid': process.pid, 'delay_seconds': 8,
            'log': str(log), 'result_file': str(result_path),
            'message': message}


def install_launcher(state, app, launcher_dir):
    package_id = verify_package()
    package = state / 'packages' / package_id
    if not package.exists():
        package.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
    verify_package(package)
    launcher = launcher_dir / 'ChatGPT mark.app'
    legacy = launcher_dir / 'mark.app'
    existing = []
    for candidate in (launcher, legacy):
        if not candidate.exists():
            continue
        info = plistlib.loads((candidate / 'Contents/Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != 'local.mark.launcher':
            raise MarkError(candidate.name + ' 已被其他应用使用，请指定另一个 --launcher-dir。')
        existing.append(candidate)
    temporary = launcher_dir / ('.ChatGPT-mark-' + uuid.uuid4().hex + '.app')
    executable = temporary / 'Contents/MacOS/mark'
    executable.parent.mkdir(parents=True, exist_ok=True)
    args = ['/usr/bin/python3', '-B', str(package / 'mark.py')]
    default_apps = {Path('/Applications/ChatGPT.app'), Path('/Applications/Codex.app'),
                    Path.home() / 'Applications/ChatGPT.app', Path.home() / 'Applications/Codex.app'}
    if app.resolve() not in {candidate.resolve() for candidate in default_apps}:
        args.extend(('--app', str(app)))
    args.extend(('--state-dir', str(state), '--gui', 'start'))
    script = temporary / 'Contents/Resources/launch.sh'
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text('#!/bin/sh\nexec ' + shlex.join(args) + '\n')
    script.chmod(0o755)
    icon = ROOT / 'assets/mark.icns'
    if not icon.is_file():
        raise MarkError('安装包缺少 mark 图标。')
    shutil.copy2(icon, temporary / 'Contents/Resources/mark.icns')
    info = {'CFBundleIdentifier': 'local.mark.launcher', 'CFBundleName': 'ChatGPT mark', 'CFBundleDisplayName': 'ChatGPT mark',
            'CFBundleExecutable': 'mark', 'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '0.1.6', 'LSUIElement': True,
            'CFBundleIconFile': 'mark.icns', 'LSArchitecturePriority': ['arm64'], 'LSMinimumSystemVersion': '11.0',
            'CFBundleGetInfoString': 'ChatGPT mark - mark and revisit conversations'}
    (temporary / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    try:
        run(['/usr/bin/xcrun', 'clang', '-arch', 'arm64', '-mmacosx-version-min=11.0',
             '-Os', '-Wall', '-Wextra', '-Werror', ROOT / 'integration/src/launcher.c', '-o', executable], capture_output=True)
        run(['/usr/bin/lipo', executable, '-verify_arch', 'arm64'], capture_output=True)
        run(['/usr/bin/codesign', '--force', '--sign', '-', temporary], capture_output=True)
        run(['/usr/bin/codesign', '--verify', '--deep', '--strict', temporary], capture_output=True)
        backups = []
        try:
            for candidate in existing:
                backup = state / 'launcher-backups' / (uuid.uuid4().hex + '.app')
                backup.parent.mkdir(parents=True, exist_ok=True)
                candidate.rename(backup)
                backups.append((candidate, backup))
            temporary.rename(launcher)
        except Exception:
            for candidate, backup in reversed(backups):
                if backup.exists() and not candidate.exists():
                    backup.rename(candidate)
            raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    atomic_json(state / "launcher.json", {"path": str(launcher)})
    # Refresh the single public launcher entry immediately after an upgrade.
    # Internal client copies live below a .metadata_never_index state directory.
    subprocess.run(['/usr/bin/mdimport', '-i', str(launcher)], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return package, launcher


def upgrade_transaction(app, state, accept=False, switch=False):
    """Hold the manager lock across build, launcher replacement and launch."""
    before = read_json(state / 'state.json', {})
    launcher = Path(read_json(state / 'launcher.json', {}).get('path', str(Path.home() / 'Applications/ChatGPT mark.app')))
    backup = state / 'launcher-backups' / ('update-' + uuid.uuid4().hex + '.app')
    if launcher.exists():
        info = plistlib.loads((launcher / 'Contents/Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != 'local.mark.launcher':
            raise MarkError('启动器路径已被其他应用使用，已停止更新。')
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(launcher, backup)
    installed = False
    try:
        record = build(app, state, accept)
        installed_result = install_launcher(state, app, launcher.parent)
        installed_launcher = Path(installed_result[1]) if installed_result else launcher
        installed = True
        result = launch_record(record, state, switch)
        prune_launcher_backups(state)
        return result
    except Exception:
        if installed:
            if installed_launcher.exists():
                failed = state / 'launcher-backups' / ('failed-' + uuid.uuid4().hex + '.app')
                failed.parent.mkdir(parents=True, exist_ok=True)
                installed_launcher.rename(failed)
            if backup.exists():
                backup.rename(launcher)
        # Keep failed build diagnostics but restore known working state.
        current = read_json(state / 'state.json', {})
        for key in ('active', 'prepared', 'previous'):
            if key in before:
                current[key] = before[key]
            else:
                current.pop(key, None)
        atomic_json(state / 'state.json', current)
        raise


def codex_cli():
    paths = [shutil.which('codex'), str(Path.home() / '.local/bin/codex')]
    for value in paths:
        if value and os.access(value, os.X_OK):
            return value
    raise MarkError('未找到 Codex CLI。可先使用界面集成，安装 CLI 后再安装标准插件。')


def install_plugin(package):
    cli = codex_cli()
    run([cli, 'plugin', 'marketplace', 'add', package])
    run([cli, 'plugin', 'add', 'codex-marks@mark'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path)
    parser.add_argument('--state-dir', type=Path, default=Path.home() / 'Library/Application Support/mark')
    parser.add_argument('--gui', action='store_true')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    sub.add_parser('status')
    sub.add_parser('update-status')
    checker = sub.add_parser('check-update')
    checker.add_argument('--force', action='store_true')
    for name in ('update', 'install-latest'):
        updater = sub.add_parser(name)
        updater.add_argument('--yes', action='store_true', help='确认下载、安装兼容更新并重启')
        updater.add_argument('--ticket')
        updater.add_argument('--accept-local-resign', action='store_true')
        updater.add_argument('--detached', action='store_true')
        updater.add_argument('--deferred-result', type=Path, help=argparse.SUPPRESS)
    for name in ('prepare', 'install', 'launch', 'rollback', 'upgrade', 'start', 'open-official'):
        p = sub.add_parser(name)
        p.add_argument('--accept-local-resign', action='store_true')
        p.add_argument('--switch', action='store_true')
        if name in ('launch', 'rollback', 'open-official'):
            p.add_argument('--detached', action='store_true', help='延迟 8 秒在独立进程中切换，适合在 Codex 内执行')
            p.add_argument('--deferred-result', type=Path, help=argparse.SUPPRESS)
        if name == 'install':
            p.add_argument('--install-plugin', action='store_true')
            p.add_argument('--launcher-dir', type=Path, default=Path.home() / 'Applications')
    args = parser.parse_args()
    state = args.state_dir.expanduser().resolve()
    try:
        if state == ROOT or ROOT in state.parents:
            raise MarkError('状态目录必须在安装包目录之外。')
        verify_package()
        prepare_state(state)
        deferred_result = getattr(args, 'deferred_result', None)
        if deferred_result:
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            time.sleep(8)
        if args.command in ('check-update', 'update-status', 'update', 'install-latest'):
            import updater
            if args.command == 'update-status':
                result = read_json(state / 'update-job.json', {'status': 'idle'})
            else:
                app = source_app(args.app)
                if args.command == 'check-update':
                    result = updater.check(sys.modules[__name__], app, state, args.force)
                else:
                    ticket = args.ticket
                    if not ticket:
                        result = updater.check(sys.modules[__name__], app, state, force=True)
                        ticket = result.get('ticket')
                    if ticket and args.yes:
                        if not args.accept_local_resign and not read_json(state / 'consent.json', {}).get('local_resign'):
                            raise MarkError('首次安装请明确接受本地签名：添加 --accept-local-resign。')
                        if args.detached:
                            with lock(state / 'update-scheduling'):
                                result = updater.schedule(sys.modules[__name__], app, state, ticket, args.accept_local_resign)
                        else:
                            with lock(state / 'update-worker'):
                                result = updater.apply(sys.modules[__name__], app, state, ticket, args.accept_local_resign)
                    elif ticket:
                        result = {'status': 'confirmation_required', 'ticket': ticket, 'message': '请确认后使用 --yes 下载、安装并重启'}
            if deferred_result:
                atomic_json(deferred_result, result)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if getattr(args, 'detached', False):
            result = schedule_switch(source_app(args.app), state, args.command, args.switch, args.accept_local_resign)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == 'status':
            result = read_json(state / 'state.json', {'status': 'not_installed'})
        else:
            app = source_app(args.app)
            if args.command == 'doctor':
                result = doctor(app)
            else:
                with lock(state):
                    if args.command == 'upgrade':
                        result = upgrade_transaction(app, state, args.accept_local_resign, args.switch)
                    elif args.command == 'open-official':
                        result = open_official(app)
                    elif args.command == 'start':
                        result = start_managed(app, state, args.accept_local_resign)
                    elif args.command == 'rollback':
                        prior = read_json(state / 'state.json', {}).get('previous')
                        if not prior:
                            raise MarkError('还没有可回退的已启动版本。当前副本和收藏数据保留。')
                        result = launch_record(prior, state, args.switch)
                    else:
                        record = build(app, state, args.accept_local_resign)
                        if args.command == 'launch':
                            result = launch_record(record, state, args.switch)
                        elif args.command == 'install':
                            launcher_dir = args.launcher_dir.expanduser().resolve()
                            if launcher_dir == ROOT or ROOT in launcher_dir.parents:
                                raise MarkError('启动入口必须安装在安装包目录之外。')
                            package, launcher = install_launcher(state, app, launcher_dir)
                            if args.install_plugin:
                                install_plugin(package)
                            result = {'status': 'installed_not_launched', 'app': record['app'], 'launcher': str(launcher), 'package': str(package)}
                        else:
                            result = {'status': 'prepared_not_launched', **record}
        if deferred_result:
            atomic_json(deferred_result, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('status') != 'unsupported_client' else 2
    except (MarkError, OSError, ValueError, subprocess.SubprocessError) as error:
        message = str(error)[:1000]
        result = {'status': 'error', 'message': message}
        if getattr(args, 'deferred_result', None):
            atomic_json(args.deferred_result, result)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        if args.gui:
            # Own launcher error only; this does not automate the Codex interface.
            escaped = message.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            subprocess.run(['/usr/bin/osascript', '-e', 'display dialog "' + escaped + '" with title "mark" buttons {"好"} default button 1'])
        return 1


if __name__ == '__main__':
    sys.exit(main())
