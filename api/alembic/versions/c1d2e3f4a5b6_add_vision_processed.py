"""add_vision_processed

Revision ID: c1d2e3f4a5b6
Revises: 2b5582550d39
Create Date: 2026-04-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = '2b5582550d39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'source_pages',
        sa.Column(
            'vision_processed',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    op.drop_column('source_pages', 'vision_processed')
