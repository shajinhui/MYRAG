"""为 documents 表添加 custom_metadata 字段

Revision ID: 2047460692d0
Revises: 
Create Date: 2026-03-17 14:09:11.881981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic 使用的版本标识符。
revision: str = '2047460692d0'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库模式。"""
    # ### 以下命令由 Alembic 自动生成 - 请按需调整！ ###
    op.add_column('documents', sa.Column('custom_metadata', sa.JSON(), nullable=True))
    # ### Alembic 命令结束 ###


def downgrade() -> None:
    """降级数据库模式。"""
    # ### 以下命令由 Alembic 自动生成 - 请按需调整！ ###
    op.drop_column('documents', 'custom_metadata')
    # ### Alembic 命令结束 ###
