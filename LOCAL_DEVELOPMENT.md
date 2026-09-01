# MYRAG 本地开发启动

## 这台 Mac 如何启动（直接照做）

这台 Mac 已经安装并配置好 Python、Node.js、pnpm、PostgreSQL、ChromaDB、项目虚拟环境和 Gemini Key，日常启动不需要重新安装依赖，也不需要 Docker。

### 第一步：启动 PostgreSQL

打开一个终端执行：

```bash
brew services start postgresql@16
pg_isready -h localhost -p 5432
```

看到 `accepting connections` 即表示数据库正常。PostgreSQL 是后台服务，这个终端执行完成后可以关闭。

### 第二步：启动 ChromaDB

打开终端一，执行：

```bash
cd /Users/shajinhui/Documents/codeAbout/Python/rag
source venv/bin/activate
chroma run --host localhost --port 8002 --path backend/data/chroma
```

这个终端需要保持运行。

### 第三步：启动后端

打开终端二，执行：

```bash
cd /Users/shajinhui/Documents/codeAbout/Python/rag
./run_bk.sh
```

看到 `Uvicorn running on http://127.0.0.1:8080` 即表示后端启动成功。这个终端需要保持运行。

### 第四步：启动前端

打开终端三，执行：

```bash
cd /Users/shajinhui/Documents/codeAbout/Python/rag
./run_fe.sh
```

看到 `Local: http://localhost:5174/` 即表示前端启动成功。这个终端需要保持运行。

### 第五步：打开项目

浏览器访问：

- MYRAG：http://localhost:5174
- API 文档：http://localhost:8080/docs

也可以在终端执行：

```bash
open http://localhost:5174
```

### 如何关闭

分别在 ChromaDB、后端、前端三个终端中按 `Ctrl+C`。PostgreSQL 可以继续在后台运行；如需关闭：

```bash
brew services stop postgresql@16
```

### 启动失败时检查

```bash
curl http://localhost:8002/api/v2/heartbeat
curl http://localhost:8080/health
```

- 第一个命令有返回：ChromaDB 正常。
- 第二个命令返回 `{"status":"healthy"}`：后端正常。
- 提示端口已被占用：通常说明对应服务已经启动，不要重复启动。

---

## 1. 环境要求

- Python 3.10+
- Node.js 18+
- pnpm 8+
- PostgreSQL
- ChromaDB

## 2. 首次配置

在项目根目录执行：

```bash
cd /Users/shajinhui/Documents/codeAbout/Python/rag
cp .env.example .env
./setup.sh
```

然后检查 `.env`：

```env
# Homebrew PostgreSQL 通常监听 5432；使用 Docker 服务时为 5433
DATABASE_URL=postgresql+asyncpg://用户名@localhost:5432/myrag

CHROMA_HOST=localhost
CHROMA_PORT=8002

LLM_PROVIDER=gemini
GOOGLE_AI_API_KEY=你的_Gemini_Key
```

如果使用 Ollama，需要将 `LLM_PROVIDER` 改为 `ollama`，并配置 `OLLAMA_HOST` 与 `OLLAMA_MODEL`。

## 3. 启动基础服务

### PostgreSQL

```bash
brew services start postgresql@16
createdb myrag 2>/dev/null || true
pg_isready -h localhost -p 5432
```

### ChromaDB

新开一个终端：

```bash
cd /Users/shajinhui/Documents/codeAbout/Python/rag
source venv/bin/activate
chroma run --host localhost --port 8002 --path backend/data/chroma
```

如果安装了 Docker，也可以用 Docker 同时启动 PostgreSQL 和 ChromaDB：

```bash
docker compose -f docker-compose.services.yml up -d
```

此方式的 PostgreSQL 端口是 `5433`，需确保 `.env` 中的端口一致。

## 4. 启动项目

终端一启动后端：

```bash
cd /Users/shajinhui/Documents/codeAbout/Python/rag
./run_bk.sh
```

终端二启动前端：

```bash
cd /Users/shajinhui/Documents/codeAbout/Python/rag
./run_fe.sh
```

## 5. 访问地址

- 前端页面：http://localhost:5174
- API 文档：http://localhost:8080/docs
- 后端健康检查：http://localhost:8080/health
- ChromaDB：http://localhost:8002/api/v2/heartbeat

## 6. 日常启动顺序

```text
PostgreSQL → ChromaDB → 后端 → 前端
```

首次执行文档解析或检索时需要加载 BGE-M3 和 BGE-Reranker，速度可能较慢，后续请求会明显加快。

## 7. 停止服务

前端、后端和 ChromaDB 所在终端按 `Ctrl+C`。如需停止 PostgreSQL：

```bash
brew services stop postgresql@16
```

如果基础服务通过 Docker 启动：

```bash
docker compose -f docker-compose.services.yml down
```

## 8. 常见问题

- 后端无法启动：检查 `.env` 中的数据库账号、数据库名和端口。
- ChromaDB 连接失败：确认 `8002` 端口已经监听。
- `venv not found`：重新执行 `./setup.sh`。
- 前端依赖缺失：进入 `frontend` 目录执行 `pnpm install`。
- Gemini 请求失败：检查 `GOOGLE_AI_API_KEY` 是否有效。
