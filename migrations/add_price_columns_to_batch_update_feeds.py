"""Add price columns to batch_update_feeds table

Revision ID: add_price_columns_to_batch_update_feeds
Revises: 
Create Date: 2024-03-19

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_price_columns_to_batch_update_feeds'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Add price_at_time and total_cost columns with default values
    op.add_column('batch_update_feeds', sa.Column('price_at_time', sa.Float(), nullable=False, server_default='0.0'))
    op.add_column('batch_update_feeds', sa.Column('total_cost', sa.Float(), nullable=False, server_default='0.0'))
    
    # Update existing rows to calculate total_cost based on quantity and feed price
    op.execute("""
        UPDATE batch_update_feeds
        SET total_cost = (
            SELECT quantity * price
            FROM feed
            WHERE feed.id = batch_update_feeds.feed_id
        )
    """)
    
    # Update price_at_time for existing rows
    op.execute("""
        UPDATE batch_update_feeds
        SET price_at_time = (
            SELECT price
            FROM feed
            WHERE feed.id = batch_update_feeds.feed_id
        )
    """)
    
    # Make columns non-nullable after setting values
    op.alter_column('batch_update_feeds', 'price_at_time', nullable=False)
    op.alter_column('batch_update_feeds', 'total_cost', nullable=False)

def downgrade():
    # Remove the columns
    op.drop_column('batch_update_feeds', 'total_cost')
    op.drop_column('batch_update_feeds', 'price_at_time') 