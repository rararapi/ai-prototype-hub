"""Persist sandboxes, operation queue with leases, and limited audit events."""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sandboxes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("template_id", sa.String(32), nullable=False),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("desired_state", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("active_operation_id", sa.Uuid(), nullable=True),
        sa.Column("preview_url", sa.String(512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.CheckConstraint("generation >= 0", name="sandbox_generation_nonnegative"),
        sa.CheckConstraint("ttl_seconds BETWEEN 60 AND 3600", name="sandbox_ttl_range"),
        sa.CheckConstraint("template_id = 'hello-web'", name="sandbox_trusted_template"),
        sa.CheckConstraint(
            "desired_state IN ('running','stopped','deleted')", name="sandbox_desired"
        ),
        sa.CheckConstraint(
            "status IN ('stopped','starting','running','stopping','deleting','deleted','failed')",
            name="sandbox_status",
        ),
    )
    op.create_index("ix_sandboxes_expires_at", "sandboxes", ["expires_at"])
    op.create_table(
        "operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sandbox_id", sa.Uuid(), sa.ForeignKey("sandboxes.id"), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.UniqueConstraint("sandbox_id", "generation", name="operation_generation_unique"),
        sa.CheckConstraint("action IN ('start','stop','delete')", name="operation_action"),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','superseded')",
            name="operation_status",
        ),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND 3", name="operation_attempt_range"),
    )
    op.create_index("ix_operations_sandbox_id", "operations", ["sandbox_id"])
    op.create_index("operation_claim", "operations", ["status", "available_at", "lease_expires_at"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sandbox_id", sa.Uuid(), sa.ForeignKey("sandboxes.id"), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_sandbox_id", "audit_events", ["sandbox_id"])


def downgrade():
    op.drop_table("audit_events")
    op.drop_table("operations")
    op.drop_table("sandboxes")
