#!/bin/bash
# Download a fresh installer from this project's main branch; never overwrite a checkout.
set -euo pipefail
umask 077
if [[ "${1:-}" == '--help' || "${1:-}" == '-h' ]]; then
  printf '%s\n' 'mark GitHub 安装器' '用法：bash install.sh [--check] [--yes] [--no-wait] [--app /Applications/ChatGPT.app]' '默认先检查兼容版本，确认后才安装并重启。--check 只检查；--yes 明确接受下载、独立副本本地签名和重启。'
  exit 0
fi
if [[ "$(/usr/bin/uname -s)" != 'Darwin' || "$(/usr/bin/uname -m)" != 'arm64' ]]; then
  printf '%s\n' '当前仅支持 macOS Apple Silicon。请在原生 arm64 终端运行，无需安装 Rosetta。' >&2
  exit 2
fi
if ! /usr/bin/xcode-select -p >/dev/null 2>&1 || ! /usr/bin/xcrun --find clang >/dev/null 2>&1; then
  printf '%s\n' '缺少 Command Line Tools。请运行 xcode-select --install，完成系统安装后重新执行。' >&2
  exit 2
fi
if ! /usr/bin/python3 --version >/dev/null 2>&1; then
  printf '%s\n' '无法运行系统 Python 3，请先修复 Command Line Tools。' >&2
  exit 2
fi
MARK_BOOTSTRAP_BASE="$HOME/Library/Application Support/mark/bootstrap"
mkdir -p "$MARK_BOOTSTRAP_BASE"
MARK_BOOTSTRAP_DIR="$(mktemp -d "$MARK_BOOTSTRAP_BASE/install.XXXXXX")"
printf '%s\n' '正在获取 mark 安装器…' "安装记录目录：$MARK_BOOTSTRAP_DIR"
if ! /usr/bin/git clone --quiet --depth 1 --branch main https://github.com/yinjialu/mark.git "$MARK_BOOTSTRAP_DIR/source"; then
  printf '%s\n' '无法连接 GitHub。请检查网络后重试；已有收藏和客户端未变。' >&2
  exit 3
fi
/usr/bin/git -C "$MARK_BOOTSTRAP_DIR/source" rev-parse HEAD > "$MARK_BOOTSTRAP_DIR/source-commit.txt"
exec /usr/bin/python3 -B "$MARK_BOOTSTRAP_DIR/source/scripts/install.py" "$@"
