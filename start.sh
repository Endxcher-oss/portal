#!/bin/sh
# 从任意目录启动 portal。额外的参数原样传给 portal。

set -eu

cd "$(dirname "$0")"

exec python3 -m portal "$@"
