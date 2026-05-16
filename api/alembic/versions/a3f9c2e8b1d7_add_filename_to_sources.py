"""add filename to sources

Revision ID: a3f9c2e8b1d7
Revises: f4e5d6c7b8a9
Create Date: 2026-05-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a3f9c2e8b1d7"
down_revision: Union[str, None] = "f4e5d6c7b8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("filename", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "filename")
