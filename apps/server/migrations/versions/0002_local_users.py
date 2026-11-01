"""Add development users, bearer sessions, sandbox ownership and explicit shares."""

import sqlalchemy as sa
from alembic import op

revision = "0002_local_users"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    # Existing records have no owner and are retained, never adopted by the first login.
    op.add_column("sandboxes", sa.Column("owner_email", sa.String(254), nullable=True))
    op.create_index("ix_sandboxes_owner_email", "sandboxes", ["owner_email"])
    op.create_table(
        "users",
        sa.Column("email", sa.String(254), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("token_digest", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(254), sa.ForeignKey("users.email"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sessions_email", "sessions", ["email"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_table(
        "sandbox_shares",
        sa.Column("sandbox_id", sa.Uuid(), sa.ForeignKey("sandboxes.id"), primary_key=True),
        sa.Column("email", sa.String(254), primary_key=True),
    )
    op.create_index("ix_sandbox_shares_email", "sandbox_shares", ["email"])


def downgrade():
    op.drop_table("sandbox_shares")
    op.drop_table("sessions")
    op.drop_table("users")
    op.drop_index("ix_sandboxes_owner_email", table_name="sandboxes")
    op.drop_column("sandboxes", "owner_email")
