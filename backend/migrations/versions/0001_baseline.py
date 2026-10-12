"""Baseline schema (v1.0 tables).

Revision ID: 0001
Revises:
"""
from alembic import op

from app.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Creates any missing tables; existing installations (created before Alembic was added) are left untouched.
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("Baseline cannot be downgraded; restore from backup instead.")
