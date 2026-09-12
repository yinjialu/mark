#!/bin/bash
set -e
MARK_PACKAGE_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
printf '%s\n' 'mark 0.1.1' '' '将从本机 ChatGPT 正式版生成独立副本，安装 mark 启动入口。标准插件可按 docs/INSTALL.md 另行安装。' '独立副本使用本地签名，并为该副本放宽库签名校验；正式版和系统安全设置不变。' '需要 macOS Apple Silicon、Command Line Tools。' ''
read -r -p '输入 install 开始安装：' MARK_INSTALL_ANSWER
if [ "$MARK_INSTALL_ANSWER" != 'install' ]; then
  exit 0
fi
/usr/bin/python3 -B "$MARK_PACKAGE_DIR/mark.py" install --accept-local-resign
printf '\n%s\n' '安装完成。打开 ~/Applications/mark.app；也可双击 Open mark.command。' '启动 mark 时会正常退出当前 Codex，再打开独立副本。'
read -r -p '按回车关闭。' MARK_INSTALL_DONE
