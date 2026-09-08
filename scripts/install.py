#!/usr/bin/env python3
"""Human-readable GitHub installation flow using the verified release updater."""
from __future__ import annotations
import argparse
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mark
import updater


def say(message):
    print(message, flush=True)


def check_result(result):
    status = result.get('status')
    if status == 'available':
        say('可安装的最新兼容版本：' + result['version'])
        return 0
    if status == 'up_to_date':
        say('已经是最新兼容版本：' + (result.get('current_version') or '未知'))
        say('日常打开 ChatGPT mark；左侧 mark → 检查更新。')
        return 0
    say(result.get('message', '检查失败，未开始安装。'))
    return 3 if status == 'offline' else 2


def wait_for_result(state, job, timeout=1200, interval=2):
    path = Path(job['result_file'])
    deadline = time.monotonic() + timeout
    previous = None
    labels = {'scheduled': '正在准备更新…', 'downloading': '正在下载并校验发布包…',
              'installing': '正在构建独立副本、签名并切换客户端…'}
    while time.monotonic() < deadline:
        result = mark.read_json(path)
        if result:
            if result.get('status') in ('complete', 'up_to_date'):
                say('安装流程完成。日常请打开 ChatGPT mark。')
                say('请选中一段回复 → mark，再到左侧 mark 页面确认收藏和原文定位。')
                return 0
            say('安装未完成：' + result.get('message', '请查看安装日志。'))
            say('日志：' + job['log'])
            return 1
        current = mark.read_json(state / 'update-job.json', {})
        # Do not mistake an unrelated earlier/later job for this invocation.
        if current.get('result_file') == str(path) and current.get('status') != previous:
            previous = current.get('status')
            if previous in labels:
                say(labels[previous])
        time.sleep(interval)
    say('等待超时，后台任务可能仍在运行；请先检查结果，避免重复安装。')
    say('结果：' + str(path))
    say('日志：' + job['log'])
    return 4


def main():
    parser = argparse.ArgumentParser(description='安装 mark 最新兼容版本，默认确认后安装并显示进度。')
    parser.add_argument('--app', help='正式客户端的非默认路径')
    parser.add_argument('--state-dir', type=Path, default=Path.home() / 'Library/Application Support/mark')
    parser.add_argument('--check', action='store_true', help='只检查环境和可用版本，不安装')
    parser.add_argument('--yes', action='store_true', help='接受下载、独立副本本地签名、启动器安装和客户端重启')
    parser.add_argument('--no-wait', action='store_true', help='安排后台安装后返回结果和日志路径')
    args = parser.parse_args()
    try:
        mark.verify_package()
        if platform.system() != 'Darwin' or platform.machine() != 'arm64':
            raise mark.MarkError('当前仅支持 macOS Apple Silicon 原生 arm64 环境。')
        subprocess.run(['/usr/bin/xcrun', '--find', 'clang'], check=True, capture_output=True)
        app = mark.source_app(args.app)
        state = args.state_dir.expanduser().resolve()
        if state == ROOT or ROOT in state.parents:
            raise mark.MarkError('安装状态目录不能位于源码包内。')
        say('正在检查正式客户端和 GitHub 兼容发布…')
        say('正式客户端：' + str(app))
        result = updater.check(mark, app, state, force=True)
        code = check_result(result)
        if code or args.check or result.get('status') != 'available':
            return code
        say('将下载校验后的发布包，在本机生成 ChatGPT mark 独立副本并本地重签名。')
        say('仅副本启用 disable-library-validation；正式应用和系统安全设置保持原样。')
        say('安装 ~/Applications/mark.app（已有自定义位置会沿用），完成后正常退出当前客户端并切换；收藏和旧副本保留。')
        if not args.yes:
            if not sys.stdin.isatty():
                say('尚未开始安装。请在交互终端运行，或明确接受上述操作后加 --yes。')
                return 2
            if input('请先结束其他运行中的任务；输入 install 确认：').strip() != 'install':
                say('已取消，未开始安装。')
                return 0
        with mark.lock(state / 'update-scheduling'):
            job = updater.schedule(mark, app, state, result['ticket'], accept=True)
        say('已安排后台安装；此时尚未完成。')
        say('结果：' + job['result_file'])
        say('日志：' + job['log'])
        if args.no_wait:
            return 0
        return wait_for_result(state, job)
    except (mark.MarkError, OSError, ValueError, subprocess.SubprocessError) as error:
        say('未完成安装：' + str(error)[:1000])
        return 1


if __name__ == '__main__':
    sys.exit(main())
