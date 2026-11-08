"""Create AeroSense tables."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sensor_readings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temperature", sa.Float()),
        sa.Column("pressure", sa.Float()),
        sa.Column("altitude", sa.Float()),
        sa.Column("co_ppm", sa.Float()),
        sa.Column("mq135_raw", sa.Float()),
        sa.Column("mq135_estimated_ppm", sa.Float()),
        sa.Column("dust_voltage", sa.Float()),
        sa.Column("dust_ug_m3", sa.Float()),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sensor_readings_id", "sensor_readings", ["id"])
    op.create_index("ix_sensor_readings_timestamp", "sensor_readings", ["timestamp"])
    op.create_index("ix_sensor_readings_source", "sensor_readings", ["source"])
    op.create_table(
        "sensor_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sensor_name", sa.String(length=80), nullable=False, unique=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True)),
        sa.Column("calibration_status", sa.String(length=80), nullable=False),
    )
    op.create_index("ix_sensor_status_sensor_name", "sensor_status", ["sensor_name"])
    op.create_table(
        "sensor_thresholds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sensor_name", sa.String(length=80), nullable=False, unique=True),
        sa.Column("warning_threshold", sa.Float(), nullable=False),
        sa.Column("critical_threshold", sa.Float(), nullable=False),
    )
    op.create_index("ix_sensor_thresholds_sensor_name", "sensor_thresholds", ["sensor_name"])
    op.create_table(
        "pollution_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alert_type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False),
        sa.Column("message", sa.String(length=300), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sensor_value", sa.Float(), nullable=False),
        sa.Column("reading_id", sa.Integer(), sa.ForeignKey("sensor_readings.id")),
    )
    op.create_index("ix_pollution_alerts_id", "pollution_alerts", ["id"])
    op.create_index("ix_pollution_alerts_alert_type", "pollution_alerts", ["alert_type"])
    op.create_index("ix_pollution_alerts_severity", "pollution_alerts", ["severity"])
    op.create_index("ix_pollution_alerts_timestamp", "pollution_alerts", ["timestamp"])


def downgrade():
    op.drop_table("pollution_alerts")
    op.drop_table("sensor_thresholds")
    op.drop_table("sensor_status")
    op.drop_table("sensor_readings")
