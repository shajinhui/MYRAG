#!/usr/bin/env bash

# MYRAG 一键启动脚本（macOS 本地开发）
#
# 用法：
#   ./start.sh          启动 PostgreSQL、ChromaDB、后端和前端
#   ./start.sh status   查看服务状态
#   ./start.sh stop     停止 MYRAG 的 ChromaDB、后端和前端

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHROMA_URL="http://localhost:8002/api/v2/heartbeat"
BACKEND_URL="http://localhost:8080/health"
FRONTEND_URL="http://localhost:5174/"

log() {
    printf '[MYRAG] %s\n' "$*"
}

error() {
    printf '[MYRAG] 错误：%s\n' "$*" >&2
}

is_ready() {
    curl -fsS --max-time 2 "$1" >/dev/null 2>&1
}

postgres_is_ready() {
    pg_isready -h localhost -p 5432 >/dev/null 2>&1
}

port_in_use() {
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

wait_for() {
    local url="$1"
    local service_name="$2"

    for ((attempt = 1; attempt <= 30; attempt++)); do
        if is_ready "$url"; then
            log "$service_name 已就绪"
            return 0
        fi
        sleep 1
    done

    error "$service_name 启动超时。"
    return 1
}

open_terminal_command() {
    local command_text="$1"

    if ! command -v osascript >/dev/null 2>&1; then
        error "未找到 osascript，无法自动打开 Terminal。"
        return 1
    fi

    osascript - "$PROJECT_DIR" "$command_text" <<'APPLESCRIPT'
on run argv
    set projectDir to item 1 of argv
    set commandText to item 2 of argv
    tell application "Terminal"
        activate
        do script "cd " & quoted form of projectDir & " && " & commandText
    end tell
end run
APPLESCRIPT
}

start_postgres() {
    if ! command -v brew >/dev/null 2>&1; then
        error "未找到 Homebrew，请先安装 PostgreSQL 或按启动文档配置数据库。"
        return 1
    fi

    if ! postgres_is_ready; then
        log "启动 PostgreSQL..."
        brew services start postgresql@16 >/dev/null 2>&1 || true
    fi

    for ((attempt = 1; attempt <= 30; attempt++)); do
        if postgres_is_ready; then
            log "PostgreSQL 已就绪"
            createdb -h localhost -p 5432 -U postgres myrag >/dev/null 2>&1 || true
            return 0
        fi
        sleep 1
    done

    error "PostgreSQL 未能在 30 秒内就绪。"
    return 1
}

start_chroma() {
    if is_ready "$CHROMA_URL"; then
        log "ChromaDB 已在运行，复用现有服务"
        return 0
    fi

    if port_in_use 8002; then
        error "8002 端口已被占用，但 ChromaDB 健康检查失败。"
        return 1
    fi

    if [[ ! -x "$PROJECT_DIR/venv/bin/chroma" ]]; then
        error "未找到 venv/bin/chroma，请先按启动文档安装依赖。"
        return 1
    fi

    log "打开 ChromaDB Terminal..."
    open_terminal_command "source venv/bin/activate && chroma run --host localhost --port 8002 --path backend/data/chroma" || return 1
    wait_for "$CHROMA_URL" "ChromaDB"
}

start_backend() {
    if is_ready "$BACKEND_URL"; then
        log "后端已在运行，复用现有服务"
        return 0
    fi

    if port_in_use 8080; then
        error "8080 端口已被占用，但后端健康检查失败。"
        return 1
    fi

    if [[ ! -x "$PROJECT_DIR/venv/bin/uvicorn" ]]; then
        error "未找到 venv/bin/uvicorn，请先按启动文档安装依赖。"
        return 1
    fi

    log "打开后端 Terminal..."
    open_terminal_command "./run_bk.sh" || return 1
    wait_for "$BACKEND_URL" "后端"
}

start_frontend() {
    if is_ready "$FRONTEND_URL"; then
        log "前端已在运行，复用现有服务"
        return 0
    fi

    if port_in_use 5174; then
        error "5174 端口已被占用，但前端访问失败。"
        return 1
    fi

    if ! command -v pnpm >/dev/null 2>&1; then
        error "未找到 pnpm，请先安装 Node.js 和 pnpm。"
        return 1
    fi

    log "打开前端 Terminal..."
    open_terminal_command "./run_fe.sh" || return 1
    wait_for "$FRONTEND_URL" "前端"
}

process_matches_service() {
    local match_service="$1"
    local match_command="$2"

    case "$match_service" in
        chroma)
            [[ "$match_command" == *"chroma run"* ]]
            ;;
        backend)
            [[ "$match_command" == *"uvicorn app.main:app"* ]]
            ;;
        frontend)
            [[ "$match_command" == *"pnpm dev"* || "$match_command" == *"vite"* ]]
            ;;
        *)
            return 1
            ;;
    esac
}

stop_port_service() {
    local stop_service="$1"
    local port="$2"
    local pids

    pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -z "$pids" ]]; then
        log "$stop_service 未运行"
        return 0
    fi

    while read -r pid; do
        [[ -z "$pid" ]] && continue
        local command_line
        command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
        if process_matches_service "$stop_service" "$command_line"; then
            log "停止 ${stop_service}（PID ${pid}）..."
            kill "$pid" >/dev/null 2>&1 || true
        else
            log "$port 端口存在其他辅助进程，已跳过：$command_line"
        fi
    done <<< "$pids"
}

show_status() {
    printf 'MYRAG 服务状态：\n'
    if postgres_is_ready; then
        printf '  PostgreSQL 已运行\n'
    else
        printf '  PostgreSQL 未运行\n'
    fi

    if is_ready "$CHROMA_URL"; then
        printf '  ChromaDB   已运行\n'
    else
        printf '  ChromaDB   未运行\n'
    fi

    if is_ready "$BACKEND_URL"; then
        printf '  后端       已运行\n'
    else
        printf '  后端       未运行\n'
    fi

    if is_ready "$FRONTEND_URL"; then
        printf '  前端       已运行\n'
    else
        printf '  前端       未运行\n'
    fi
}

start_all() {
    start_postgres || return 1
    start_chroma || return 1
    start_backend || return 1
    start_frontend || return 1

    log "MYRAG 启动完成"
    log "项目地址：http://localhost:5174"
    log "API 文档：http://localhost:8080/docs"
    open "$FRONTEND_URL" >/dev/null 2>&1 || true
}

case "${1:-start}" in
    start)
        start_all
        ;;
    stop)
        stop_port_service frontend 5174
        stop_port_service backend 8080
        stop_port_service chroma 8002
        log "应用服务已停止；PostgreSQL 保持后台运行。"
        ;;
    status)
        show_status
        ;;
    *)
        printf '用法：%s [start|stop|status]\n' "$0"
        exit 1
        ;;
esac
