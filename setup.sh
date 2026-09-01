#!/bin/bash
# ============================================================
# MYRAG —— 本地开发环境搭建
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo "  MYRAG — Local Development Setup"
echo "============================================"
echo ""

# -----------------------------------------------------------
# 1. 检查前置条件
# -----------------------------------------------------------
echo "[1/7] Checking prerequisites..."

# Python 环境
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    echo "ERROR: Python 3.10+ required (found $PY_VERSION)"
    exit 1
fi
echo "  Python $PY_VERSION"

# Node 环境
if ! command -v node &>/dev/null; then
    echo "ERROR: node not found. Install Node.js 18+ first."
    exit 1
fi
NODE_MAJOR=$(node -v | sed 's/v//' | cut -d. -f1)
if [ "$NODE_MAJOR" -lt 18 ]; then
    echo "ERROR: Node.js 18+ required (found $(node -v))"
    exit 1
fi
echo "  Node $(node -v)"

# pnpm 环境
if ! command -v pnpm &>/dev/null; then
    echo "ERROR: pnpm not found. Install: npm install -g pnpm"
    exit 1
fi
echo "  pnpm $(pnpm -v)"

# Docker（可选）
if command -v docker &>/dev/null; then
    echo "  Docker $(docker --version | cut -d' ' -f3 | tr -d ',')"
    HAS_DOCKER=true
else
    echo "  Docker: not found (PostgreSQL + ChromaDB must be started manually)"
    HAS_DOCKER=false
fi

echo ""

# -----------------------------------------------------------
# 2. 创建 Python 虚拟环境
# -----------------------------------------------------------
echo "[2/7] Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  Created venv/"
else
    echo "  venv/ already exists"
fi
source venv/bin/activate

# -----------------------------------------------------------
# 3. 安装 Python 依赖
# -----------------------------------------------------------
echo "[3/7] Installing Python dependencies..."
pip install -q --upgrade pip
pip install -q -r backend/requirements.txt
echo "  Done."

# -----------------------------------------------------------
# 4. 不存在时创建 .env
# -----------------------------------------------------------
echo "[4/7] Checking .env configuration..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  Created .env from .env.example"
    echo "  >>> IMPORTANT: Edit .env and set GOOGLE_AI_API_KEY <<<"
else
    echo "  .env already exists"
fi

# -----------------------------------------------------------
# 5. 启动服务（Docker）
# -----------------------------------------------------------
echo "[5/7] Starting database services..."
if [ "$HAS_DOCKER" = true ]; then
    docker compose -f docker-compose.services.yml up -d
    echo "  Waiting for PostgreSQL to be ready..."
    for i in $(seq 1 30); do
        if docker exec myrag-postgres pg_isready -U postgres &>/dev/null; then
            echo "  PostgreSQL ready."
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo "  WARNING: PostgreSQL not ready after 30s. Check docker logs."
        fi
        sleep 1
    done
else
    echo "  Skipped (no Docker). Ensure PostgreSQL (port 5433) and ChromaDB (port 8002) are running."
fi

# -----------------------------------------------------------
# 6. 下载机器学习模型（可选）
# -----------------------------------------------------------
echo ""
echo "[6/7] ML models (~2.5GB total):"
echo "  - BAAI/bge-m3 (embedding, ~1.4GB)"
echo "  - BAAI/bge-reranker-v2-m3 (reranker, ~1.1GB)"
echo ""
read -p "  Download models now? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[yY]$ ]]; then
    echo "  Downloading models (this may take a few minutes)..."
    python backend/scripts/download_models.py
else
    echo "  Skipped. Models will be downloaded on first use."
fi

# -----------------------------------------------------------
# 7. 安装前端依赖
# -----------------------------------------------------------
echo "[7/7] Installing frontend dependencies..."
cd frontend
pnpm install
cd ..

# -----------------------------------------------------------
# 完成
# -----------------------------------------------------------
echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "  Start backend:   ./run_bk.sh"
echo "  Start frontend:  ./run_fe.sh"
echo "  Open:            http://localhost:5174"
echo ""
echo "  Or use Docker:   docker compose up -d"
echo ""
