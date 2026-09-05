
"""MAG 9.5 upgrade: experiment arms, webhook state, outbox, learning, key hashes.

Revision ID: 002_mag95
Revises: 001_baseline
"""
from alembic import op
import sqlalchemy as sa

revision: str = "002_mag95"
down_revision = "001_baseline"
branch_labels = None
depends_on = None


def _col(table, name, type_, **kw):
    try:
        op.add_column(table, sa.Column(name, type_, **kw))
    except Exception:
        pass  # idempotent: column already exists


def upgrade():
    _col("merchants", "api_key_hash", sa.String(), nullable=True)
    _col("merchants", "api_key_prefix", sa.String(), nullable=True)
    _col("orders", "campaign_id", sa.String(), nullable=True)
    _col("webhook_events", "status", sa.String(), server_default="received")
    _col("webhook_events", "attempts", sa.Integer(), server_default="0")
    _col("webhook_events", "last_error", sa.Text(), server_default="")
    _col("approvals", "campaign_id", sa.String(), nullable=True)
    _col("approvals", "action_type", sa.String(), nullable=True)
    _col("approvals", "expires_at", sa.DateTime(), nullable=True)
    _col("campaigns", "expected_incremental_margin", sa.Integer(), server_default="0")
    _col("campaigns", "budget_paise", sa.Integer(), server_default="0")
    _col("campaigns", "cost_paise", sa.Integer(), server_default="0")
    _col("campaigns", "policy_version", sa.Integer(), server_default="1")
    _col("campaigns", "experiment_ratio", sa.Float(), server_default="0.1")
    _col("campaigns", "simulation_mode", sa.Boolean(), server_default=sa.text("TRUE"))
    _col("campaigns", "approved_amount", sa.Integer(), nullable=True)
    _col("campaigns", "action_hash", sa.String(), nullable=True)
    _col("campaign_audiences", "customer_id", sa.String(), nullable=True)
    _col("campaign_audiences", "group", sa.String(), nullable=True)
    _col("campaign_audiences", "assigned_at", sa.DateTime(), nullable=True)
    _col("campaign_audiences", "exposed_at", sa.DateTime(), nullable=True)
    _col("campaign_audiences", "viewed_at", sa.DateTime(), nullable=True)
    _col("campaign_audiences", "clicked_at", sa.DateTime(), nullable=True)
    _col("campaign_audiences", "added_at", sa.DateTime(), nullable=True)
    _col("campaign_audiences", "purchased_at", sa.DateTime(), nullable=True)
    _col("campaign_audiences", "order_id", sa.String(), nullable=True)
    _col("campaign_audiences", "is_simulated", sa.Boolean(), server_default=sa.text("FALSE"))
    for f in ("treatment_eligible", "treatment_purchases", "treatment_revenue",
              "treatment_margin", "control_eligible", "control_purchases",
              "control_revenue", "control_margin", "incremental_orders",
              "incremental_revenue", "incremental_margin"):
        _col("campaign_metrics", f, sa.Integer(), server_default="0")
    _col("campaign_metrics", "ci_low", sa.Float(), nullable=True)
    _col("campaign_metrics", "ci_high", sa.Float(), nullable=True)
    _col("campaign_metrics", "sample_adequate", sa.Boolean(), server_default=sa.text("FALSE"))
    _col("campaign_metrics", "simulation_mode", sa.Boolean(), server_default=sa.text("TRUE"))
    # learning_state table
    try:
        op.create_table(
            "learning_state",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("merchant_id", sa.String(), sa.ForeignKey("merchants.id"), index=True),
            sa.Column("key", sa.String()),
            sa.Column("alpha", sa.Float(), server_default="2.0"),
            sa.Column("beta", sa.Float(), server_default="2.0"),
            sa.Column("observations", sa.Integer(), server_default="0"),
            sa.Column("successes", sa.Integer(), server_default="0"),
            sa.Column("prev_mean", sa.Float(), nullable=True),
            sa.Column("mean", sa.Float(), server_default="0.08"),
            sa.Column("ci_low", sa.Float(), nullable=True),
            sa.Column("ci_high", sa.Float(), nullable=True),
            sa.Column("source", sa.String(), server_default="prior"),
            sa.Column("updated_at", sa.DateTime()),
            sa.UniqueConstraint("merchant_id", "key", name="uq_learning_merchant_key"),
        )
    except Exception:
        pass
    # uniqueness + indexes (best effort per backend)
    for stmt in (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_campaign_customer ON campaign_audiences (campaign_id, customer_id)",
        "CREATE INDEX IF NOT EXISTS ix_audience_campaign_group ON campaign_audiences (campaign_id, \"group\")",
        "CREATE INDEX IF NOT EXISTS ix_webhook_status ON webhook_events (status)",
        "CREATE INDEX IF NOT EXISTS ix_orders_merchant_created ON orders (merchant_id, created_at)",
    ):
        try:
            op.execute(sa.text(stmt))
        except Exception:
            pass


def downgrade():
    pass
