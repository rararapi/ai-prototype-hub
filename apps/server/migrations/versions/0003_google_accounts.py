"""Provision Google accounts separately from users created by development login."""

import sqlalchemy as sa
from alembic import op

revision = "0003_google_accounts"
down_revision = "0002_local_users"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "google_accounts",
        sa.Column("email", sa.String(254), primary_key=True),
        sa.Column("subject", sa.String(255), nullable=True, unique=True),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    # Existing bearer sessions keep the local-only NULL discriminator.
    op.add_column("sessions", sa.Column("google_subject", sa.String(255), nullable=True))


def downgrade():
    # Never reinterpret a verified Google session as a development session.
    op.execute("DELETE FROM sessions WHERE google_subject IS NOT NULL")
    op.drop_column("sessions", "google_subject")
    op.drop_table("google_accounts")
