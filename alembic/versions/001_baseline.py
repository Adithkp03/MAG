
"""baseline 0.18 - all tables

Revision ID: 001_baseline
Revises: 
Create Date: 2026-09-03
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001_baseline"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Baseline: create_all via Base.metadata - for fresh DB do:
    # from backend.app.core.database import Base, engine; Base.metadata.create_all(bind=engine)
    # This revision is a marker; real schema is managed via create_all + additive ALTERs in main.py
    # For production, generate with: alembic revision --autogenerate -m "add xyz"
    pass

def downgrade():
    pass
