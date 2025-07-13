"""Add price columns to batch_update_item

Revision ID: add_price_columns
Revises: 
Create Date: 2024-03-19

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_price_columns'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Add price_at_time and total_cost columns to batch_update_item table
    op.add_column('batch_update_item', sa.Column('price_at_time', sa.Float(), nullable=False, server_default='0.0'))
    op.add_column('batch_update_item', sa.Column('total_cost', sa.Float(), nullable=False, server_default='0.0'))

def downgrade():
    # Remove the columns if needed to rollback
    op.drop_column('batch_update_item', 'total_cost')
    op.drop_column('batch_update_item', 'price_at_time') 