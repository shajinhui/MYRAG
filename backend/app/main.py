"""
MYRAG —— 独立的“知识库 + RAG”应用。
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import logging

from datetime import datetime, timedelta

from sqlalchemy import text, update

from app.core.config import settings
from app.core.database import engine, Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MYRAG API...")
    import os
    auto_create = os.environ.get("AUTO_CREATE_TABLES", "true").lower() == "true"
    if auto_create:
        async with engine.begin() as conn:
            # 检查表是否已存在（例如 alembic_version）
            result = await conn.execute(
                text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'alembic_version');")
            )
            is_initialized = result.scalar()

            if not is_initialized:
                schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
                if os.path.exists(schema_path):
                    with open(schema_path, "r", encoding="utf-8") as f:
                        schema_sql = f.read()
                    
                    # 逐条拆分并执行，避免 asyncpg 的多语句问题
                    for statement in schema_sql.split(';'):
                        stmt = statement.strip()
                        if stmt:
                            await conn.execute(text(stmt))
                    logger.info("Database tables created from schema.sql")
                    
                    # 写入 Alembic 版本号
                    await conn.execute(text("INSERT INTO public.alembic_version (version_num) VALUES ('7f3c2a91b5e4') ON CONFLICT DO NOTHING;"))
                else:
                    await conn.run_sync(Base.metadata.create_all)
                    logger.info("Database tables created/verified (Base.metadata.create_all)")
            else:
                logger.info("Database is already initialized.")

        # 恢复上次运行遗留的卡死文档
        from app.models.document import Document, DocumentStatus
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy import select as sa_select
        async with AsyncSession(engine) as session:
            timeout = settings.MYRAG_PROCESSING_TIMEOUT_MINUTES
            cutoff = datetime.utcnow() - timedelta(minutes=timeout)
            stale_statuses = [
                DocumentStatus.PROCESSING,
                DocumentStatus.PARSING,
                DocumentStatus.INDEXING,
            ]
            result = await session.execute(
                update(Document)
                .where(
                    Document.status.in_(stale_statuses),
                    Document.updated_at < cutoff,
                )
                .values(
                    status=DocumentStatus.FAILED,
                    error_message=f"Processing timeout ({timeout}min). Click Analyze to retry.",
                )
                .returning(Document.id)
            )
            stale_ids = [row[0] for row in result.fetchall()]
            if stale_ids:
                await session.commit()
                logger.warning(f"Recovered {len(stale_ids)} stale documents: {stale_ids}")
    else:
        logger.info("AUTO_CREATE_TABLES=false — skipping auto-migration")
    yield
    logger.info("Shutting down...")
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    description="MYRAG — Knowledge Base with semantic search, knowledge graph, and LLM chat",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    redirect_slashes=False,
)

# CORS 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    return {"status": "ready"}


# API 路由
from app.api.router import api_router  # noqa: E402

app.include_router(api_router, prefix="/api/v1")

# 静态文件 —— MYRAG（Docling）提取的文档图片
_docling_data = Path(__file__).resolve().parent.parent / "data" / "docling"
_docling_data.mkdir(parents=True, exist_ok=True)
app.mount("/static/doc-images", StaticFiles(directory=str(_docling_data)), name="static_doc_images")

# 导入模型，让 SQLAlchemy 完成注册
from app.models import knowledge_base, document, chat_message  # noqa: E402, F401
