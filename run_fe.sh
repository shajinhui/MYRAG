#!/bin/bash
# MYRAG 前端 —— 启动 Vite 开发服务器
set -e

# 如果存在则加载 nvm
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

cd "$(dirname "$0")/frontend"

# 需要时安装依赖
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    pnpm install
fi

echo "Starting MYRAG frontend on port 5174..."
pnpm dev
