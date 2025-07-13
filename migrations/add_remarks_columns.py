"""add remarks columns to batch_update

Revision ID: add_remarks_columns
Revises: 
Create Date: 2024-03-19

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_remarks_columns'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Add remarks and remarks_priority columns to batch_update table
    op.add_column('batch_update', sa.Column('remarks', sa.Text(), nullable=True))
    op.add_column('batch_update', sa.Column('remarks_priority', sa.String(20), nullable=True, server_default='low'))

def downgrade():
    # Remove the columns if needed to rollback
    op.drop_column('batch_update', 'remarks_priority')
    op.drop_column('batch_update', 'remarks') 