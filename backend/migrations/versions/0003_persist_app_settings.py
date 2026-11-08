"""Persist demo mode and optional demo station location."""
from alembic import op
import sqlalchemy as sa

revision = "0003_persist_app_settings"
down_revision = "0002_reading_locations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_settings",
        sa.Column("setting_key", sa.String(length=80), primary_key=True),
        sa.Column("value", sa.String(length=1000), nullable=False),
    )


def downgrade():
    op.drop_table("app_settings")
