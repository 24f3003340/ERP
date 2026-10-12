"""IGST support, purchase cancel / supplier returns.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

from app.models import Base

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

COLUMNS = [
    ("customers", sa.Column("state_code", sa.String(4), nullable=False, server_default="")),
    ("suppliers", sa.Column("state_code", sa.String(4), nullable=False, server_default="")),
    ("sales_invoices", sa.Column("is_igst", sa.Boolean, nullable=False, server_default=sa.false())),
    ("purchase_invoices", sa.Column("status", sa.String(12), nullable=False, server_default="posted")),
    ("purchase_invoices", sa.Column("credited", sa.BigInteger, nullable=False, server_default="0")),
    ("purchase_invoices", sa.Column("is_igst", sa.Boolean, nullable=False, server_default=sa.false())),
    ("purchase_invoices", sa.Column("cancel_reason", sa.String(200), nullable=True)),
    ("purchase_lines", sa.Column("returned_qty", sa.Numeric(14, 3), nullable=False, server_default="0")),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, col in COLUMNS:  # idempotent: fresh installs already have these from the baseline
        if table in insp.get_table_names() and col.name not in {c["name"] for c in insp.get_columns(table)}:
            op.add_column(table, col)
    Base.metadata.create_all(bind)  # new tables (purchase_returns, ...)


def downgrade() -> None:
    raise RuntimeError("Downgrade not supported; restore from backup instead.")
