"""Add quantity_per_unit_at_time column to batch update tables

Revision ID: add_quantity_per_unit_at_time
Revises: d74177269ee2
Create Date: 2024-03-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'add_quantity_per_unit_at_time'
down_revision = 'd74177269ee2'
branch_labels = None
depends_on = None

def upgrade():
    # Get the inspector
    conn = op.get_bind()
    inspector = inspect(conn)
    
    # Check if column exists in batch_update_feeds
    batch_update_feeds_columns = [col['name'] for col in inspector.get_columns('batch_update_feeds')]
    if 'quantity_per_unit_at_time' not in batch_update_feeds_columns:
        # Create a new table with the desired schema
        op.create_table(
            'batch_update_feeds_new',
            sa.Column('batch_update_id', sa.Integer, sa.ForeignKey('batch_update.id'), primary_key=True),
            sa.Column('feed_id', sa.Integer, sa.ForeignKey('feed.id'), primary_key=True),
            sa.Column('quantity', sa.Float, nullable=False),
            sa.Column('quantity_per_unit_at_time', sa.Float, nullable=False),
            sa.Column('price_at_time', sa.Float, nullable=False),
            sa.Column('total_cost', sa.Float, nullable=False)
        )
        
        # Copy data from the old table to the new table
        op.execute("""
            INSERT INTO batch_update_feeds_new (batch_update_id, feed_id, quantity, quantity_per_unit_at_time, price_at_time, total_cost)
            SELECT batch_update_id, feed_id, quantity, weight, price_at_time, total_cost
            FROM batch_update_feeds
        """)
        
        # Drop the old table
        op.drop_table('batch_update_feeds')
        
        # Rename the new table to the original name
        op.rename_table('batch_update_feeds_new', 'batch_update_feeds')
    
    # Check if column exists in batch_update_item
    batch_update_item_columns = [col['name'] for col in inspector.get_columns('batch_update_item')]
    if 'quantity_per_unit_at_time' not in batch_update_item_columns:
        # Add quantity_per_unit_at_time column to batch_update_item
        op.add_column('batch_update_item', sa.Column('quantity_per_unit_at_time', sa.Float(), nullable=True))
        
        # Update existing rows to set quantity_per_unit_at_time based on item type
        op.execute("""
            UPDATE batch_update_item
            SET quantity_per_unit_at_time = (
                CASE 
                    WHEN item_type = 'medicine' THEN (
                        SELECT quantity_per_unit
                        FROM medicine
                        WHERE medicine.id = batch_update_item.item_id
                    )
                    WHEN item_type = 'health_material' THEN (
                        SELECT quantity_per_unit
                        FROM health_material
                        WHERE health_material.id = batch_update_item.item_id
                    )
                    WHEN item_type = 'vaccine' THEN (
                        SELECT quantity_per_unit
                        FROM vaccine
                        WHERE vaccine.id = batch_update_item.item_id
                    )
                END
            )
        """)
        
        # Make column non-nullable after setting values
        op.alter_column('batch_update_item', 'quantity_per_unit_at_time', nullable=False)

def downgrade():
    # Get the inspector
    conn = op.get_bind()
    inspector = inspect(conn)
    
    # Check if column exists in batch_update_feeds
    batch_update_feeds_columns = [col['name'] for col in inspector.get_columns('batch_update_feeds')]
    if 'quantity_per_unit_at_time' in batch_update_feeds_columns:
        # Remove quantity_per_unit_at_time column from batch_update_feeds
        op.drop_column('batch_update_feeds', 'quantity_per_unit_at_time')
    
    # Check if column exists in batch_update_item
    batch_update_item_columns = [col['name'] for col in inspector.get_columns('batch_update_item')]
    if 'quantity_per_unit_at_time' in batch_update_item_columns:
        # Remove quantity_per_unit_at_time column from batch_update_item
        op.drop_column('batch_update_item', 'quantity_per_unit_at_time') 