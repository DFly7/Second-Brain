"""add_monitor_cursor

Revision ID: 7b7d062f11a5
Revises: c1d2e3f4a5b6
Create Date: 2026-05-02 14:14:17.344757

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7b7d062f11a5'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'chat_sessions',
        sa.Column('last_monitored_message_id', sa.String(), nullable=True),
    )
    op.create_foreign_key(
        'fk_chat_sessions_last_monitored_message_id',
        'chat_sessions',
        'chat_messages',
        ['last_monitored_message_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_chat_sessions_last_monitored_message_id',
        'chat_sessions',
        type_='foreignkey',
    )
    op.drop_column('chat_sessions', 'last_monitored_message_id')
