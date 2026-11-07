"""Persist owned AI plans, idempotent generation reservations, and quota mutex."""

import sqlalchemy as sa
from alembic import op

revision = "0004_ai_applications"
down_revision = "0003_google_accounts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_applications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_email", sa.String(254), sa.ForeignKey("users.email"), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("brief", sa.JSON(), nullable=False),
        sa.Column("summary", sa.String(1000), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft','ready','deleted')", name="ai_application_status"),
        sa.CheckConstraint("revision >= 1", name="ai_application_revision"),
    )
    op.create_index("ix_ai_applications_owner_email", "ai_applications", ["owner_email"])
    op.create_table(
        "ai_generations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_email", sa.String(254), sa.ForeignKey("users.email"), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("ai_applications.id"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("token", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')", name="ai_generation_status"
        ),
    )
    op.create_index("ai_generation_quota", "ai_generations", ["owner_email", "created_at"])
    quota = op.create_table("ai_quotas", sa.Column("id", sa.String(32), primary_key=True))
    op.bulk_insert(quota, [{"id": "global"}])


def downgrade():
    op.drop_table("ai_generations")
    op.drop_table("ai_applications")
    op.drop_table("ai_quotas")
