
"""baseline 0.18+9.5 - full schema via models (clean installs).

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
    # Clean install: create the full schema from models. Existing DBs that
    # predate alembic already have these tables -> create_all is a no-op.
    try:
        from backend.app.core.database import Base
        from backend.app.models import entities  # noqa: F401
    except ImportError:
        try:
            from app.core.database import Base
            from app.models import entities  # noqa: F401
        except ImportError:
            return
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    pass
