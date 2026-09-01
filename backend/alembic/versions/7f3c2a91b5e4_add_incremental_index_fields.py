"""给文档补上增量索引需要的指纹字段。

Revision ID: 7f3c2a91b5e4
Revises: 2047460692d0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7f3c2a91b5e4"
down_revision: Union[str, Sequence[str], None] = "2047460692d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("content_hash", sa.String(64), nullable=True))
    op.add_column("documents", sa.Column("index_fingerprint", sa.String(64), nullable=True))
    op.add_column("documents", sa.Column("indexed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])


def downgrade() -> None:
    op.drop_index("ix_documents_content_hash", table_name="documents")
    op.drop_column("documents", "indexed_at")
    op.drop_column("documents", "index_fingerprint")
    op.drop_column("documents", "content_hash")
