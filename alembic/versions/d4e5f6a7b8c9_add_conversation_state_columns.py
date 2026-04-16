"""Add Rosetta conversation state columns to conversations.

Adds `active_entity` (last cell ref / metric referenced) and
`scenario_overrides` (JSONB dict of what-if overrides) so the Rosetta
coordinator can persist multi-turn state.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Rosetta conversation state columns."""
    op.add_column(
        "conversations",
        sa.Column("active_entity", sa.Text(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "scenario_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "scenario_overrides")
    op.drop_column("conversations", "active_entity")
