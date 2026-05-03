"""drop_vision_processed

Revision ID: f4e5d6c7b8a9
Revises: 7b7d062f11a5
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f4e5d6c7b8a9"
down_revision: Union[str, None] = "7b7d062f11a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("source_pages", "vision_processed")


def downgrade() -> None:
    op.add_column(
        "source_pages",
        sa.Column(
            "vision_processed",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
