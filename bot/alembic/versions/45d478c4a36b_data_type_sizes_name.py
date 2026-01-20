"""data_type sizes.name

Revision ID: 45d478c4a36b
Revises: 060deeef533d
Create Date: 2025-09-29 14:00:07.112096

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '45d478c4a36b'
down_revision: Union[str, Sequence[str], None] = '060deeef533d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Если вы хотите конвертировать текст в число
    op.alter_column(
        "sizes",
        "name",
        type_=sa.Numeric(2, 1),
        postgresql_using="name::numeric(2,1)",
        schema="public"
    )

def downgrade() -> None:
    # Откат обратно в String
    op.alter_column(
        "sizes",
        "name",
        type_=sa.String(50),
        postgresql_using="name::varchar",
        schema="public"
    )