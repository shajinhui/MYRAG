import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# 这是 Alembic Config 对象，提供
# 对当前 .ini 文件中值的访问。
config = context.config

# 解析配置文件，用于 Python 日志。
# 这一行基本完成 logger 的设置。
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 在这里添加模型的 MetaData 对象
# 以支持 'autogenerate'
import os
import sys

# 将 'alembic' 的父目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import Base
from app.core.config import settings

# 在这里导入全部模型，让 Alembic 能够发现它们
from app.models.document import Document, DocumentImage, DocumentTable
from app.models.knowledge_base import KnowledgeBase
from app.models.chat_message import ChatMessage

target_metadata = Base.metadata

# 配置中的其他值，可根据 env.py 的需要获取，
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
# 例如：
# my_important_option = config.get_main_option("my_important_option")
# ... 等等。


def run_migrations_offline() -> None:
    """以 'offline' 模式运行迁移。

    这里只用 URL 配置上下文，不创建 Engine；
    当然在此处使用 Engine 也可以。跳过 Engine 创建后，
    甚至不需要 DBAPI 可用。

    这里的 context.execute() 调用会把给定字符串输出到
    脚本输出中。

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """用项目已经在用的 asyncpg 跑迁移，别再额外找一个不存在的驱动。"""
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
