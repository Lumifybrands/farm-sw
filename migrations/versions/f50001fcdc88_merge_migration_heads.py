"""Merge migration heads

Revision ID: f50001fcdc88
Revises: 4ec3b040e355, 5f9b4c2b1a3e
Create Date: 2025-07-26 12:19:16.724375

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f50001fcdc88'
down_revision = ('4ec3b040e355', '5f9b4c2b1a3e')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
