"""add farm batch number

Revision ID: add_farm_batch_number
Revises: 2001e5b1038a
Create Date: 2024-03-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_farm_batch_number'
down_revision = '2001e5b1038a'
branch_labels = None
depends_on = None

def upgrade():
    # Add farm_batch_number column
    op.add_column('batch', sa.Column('farm_batch_number', sa.Integer(), nullable=True))
    
    # Update existing batches with farm-specific numbers
    connection = op.get_bind()
    farms = connection.execute('SELECT id FROM farm').fetchall()
    
    for farm in farms:
        farm_id = farm[0]
        # Get all batches for this farm ordered by creation date
        batches = connection.execute(
            'SELECT id FROM batch WHERE farm_id = ? ORDER BY created_at',
            (farm_id,)
        ).fetchall()
        
        # Assign sequential numbers
        for index, batch in enumerate(batches, 1):
            connection.execute(
                'UPDATE batch SET farm_batch_number = ? WHERE id = ?',
                (index, batch[0])
            )
    
    # Make the column non-nullable after populating data
    op.alter_column('batch', 'farm_batch_number',
                    existing_type=sa.Integer(),
                    nullable=False)

def downgrade():
    op.drop_column('batch', 'farm_batch_number') 