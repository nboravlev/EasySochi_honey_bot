"""alter sizes volume_ml nullable true

Revision ID: 060deeef522d
Revises: 060deeef522c
Create Date: 2025-09-27 10:40:23.516101

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.

revision: str = '060deeef533d'
down_revision: Union[str, Sequence[str], None] = '060deeef522c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.alter_column(
        "sizes",
        "volume_ml",
        schema="public",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "sizes",
        "volume_ml",
        schema="public",
        existing_type=sa.Integer(),
        nullable=False,
    )