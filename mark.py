#!/usr/bin/env python3
"""Portable, version-pinned local client installer. No network or bookmark writes."""
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
    for app in (Path('/Applications/Codex.app'), Path('/Applications/ChatGPT.app'),
                Path.home() / 'Applications/Codex.app', Path.home() / 'Applications/ChatGPT.app'):
        if app.exists():
            try:
                if plistlib.loads((app / 'Contents/Info.plist').read_bytes()).get('CFBundleIdentifier') == 'com.openai.codex':
                    return app.resolve()
            except (OSError, ValueError):
                pass
    raise MarkError('未找到正式 Codex。请先安装，或通过 --app 指定应用路径。')


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


def remember_build(state, record):
    # Committing a prepared build does not change the last successfully launched build.
    current = read_json(state / 'state.json', {})
    current.update(prepared=record, checked_at=stamp())
    atomic_json(state / 'state.json', current)


def build(app, state, accept=False):
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
        info_path = target / 'Contents/Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info.update(CFBundleName='ChatGPT mark', CFBundleDisplayName='ChatGPT mark')
        info_path.write_bytes(plistlib.dumps(info))
        sign_copy(app, target, check['adapter'], directory)
        record = {'app': str(target), 'version': check['version'], 'source_app': str(app), 'source_header_sha256': check['source_header_sha256'],
                  'patched_header_sha256': report['patched_header_sha256'], 'package_id': package_id, 'created_at': stamp(), 'adapter_id': check['adapter']['id']}
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


def promote(state, record):
    data = read_json(state / 'state.json', {})
    if data.get('active') and data['active']['app'] != record['app']:
        data['previous'] = data['active']
    data.update(active=record, prepared=record, last_launch=stamp())
    atomic_json(state / 'state.json', data)


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
    return {'status': 'switch_scheduled', 'pid': process.pid, 'delay_seconds': 8,
            'log': str(log), 'result_file': str(result_path),
            'message': '切换已安排；这不是启动成功。请检查 result_file 的最终状态。'}


def install_launcher(state, app, launcher_dir):
    package_id = verify_package()
    package = state / 'packages' / package_id
    if not package.exists():
        package.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
    verify_package(package)
    launcher = launcher_dir / 'mark.app'
    previous = None
    if launcher.exists():
        info = plistlib.loads((launcher / 'Contents/Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != 'local.mark.launcher':
            raise MarkError('mark.app 名称已被其他应用使用，请指定另一个 --launcher-dir。')
        previous = state / 'launcher-backups' / uuid.uuid4().hex
        previous.parent.mkdir(parents=True, exist_ok=True)
    temporary = launcher_dir / ('.mark-' + uuid.uuid4().hex + '.app')
    executable = temporary / 'Contents/MacOS/mark'
    executable.parent.mkdir(parents=True, exist_ok=True)
    args = ['/usr/bin/python3', '-B', str(package / 'mark.py'), '--app', str(app), '--state-dir', str(state), '--gui', 'launch', '--switch']
    script = temporary / 'Contents/Resources/launch.sh'
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text('#!/bin/sh\nexec ' + shlex.join(args) + '\n')
    script.chmod(0o755)
    info = {'CFBundleIdentifier': 'local.mark.launcher', 'CFBundleName': 'mark', 'CFBundleDisplayName': 'mark',
            'CFBundleExecutable': 'mark', 'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '0.1.0', 'LSUIElement': True,
            'LSArchitecturePriority': ['arm64'], 'LSMinimumSystemVersion': '11.0'}
    (temporary / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    try:
        run(['/usr/bin/xcrun', 'clang', '-arch', 'arm64', '-mmacosx-version-min=11.0',
             '-Os', '-Wall', '-Wextra', '-Werror', ROOT / 'integration/src/launcher.c', '-o', executable], capture_output=True)
        run(['/usr/bin/lipo', executable, '-verify_arch', 'arm64'], capture_output=True)
        run(['/usr/bin/codesign', '--force', '--sign', '-', temporary], capture_output=True)
        run(['/usr/bin/codesign', '--verify', '--deep', '--strict', temporary], capture_output=True)
        if previous:
            launcher.rename(previous)
        try:
            temporary.rename(launcher)
        except Exception:
            if previous:
                previous.rename(launcher)
            raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return package, launcher


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
    for name in ('prepare', 'install', 'launch', 'rollback'):
        p = sub.add_parser(name)
        p.add_argument('--accept-local-resign', action='store_true')
        p.add_argument('--switch', action='store_true')
        if name in ('launch', 'rollback'):
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
        deferred_result = getattr(args, 'deferred_result', None)
        if deferred_result:
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            time.sleep(8)
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
                    if args.command == 'rollback':
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
