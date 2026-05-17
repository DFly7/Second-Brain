"""add title description to sources

Revision ID: e5f6a7b8c901
Revises: a3f9c2e8b1d7
Create Date: 2026-05-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5f6a7b8c901"
down_revision: Union[str, None] = "a3f9c2e8b1d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("title", sa.String(), nullable=True))
    op.add_column("sources", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "description")
    op.drop_column("sources", "title")
