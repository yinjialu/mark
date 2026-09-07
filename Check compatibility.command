#!/bin/bash
MARK_PACKAGE_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
/usr/bin/python3 -B "$MARK_PACKAGE_DIR/mark.py" doctor
read -r -p '按回车关闭。' MARK_CHECK_DONE
