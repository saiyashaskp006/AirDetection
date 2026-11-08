"""Add site coordinates and particulate-size metadata to readings."""
from alembic import op
import sqlalchemy as sa

revision = "0002_reading_locations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sensor_readings", sa.Column("dust_particle_size", sa.String(length=12)))
    op.add_column("sensor_readings", sa.Column("location_name", sa.String(length=120)))
    op.add_column("sensor_readings", sa.Column("latitude", sa.Float()))
    op.add_column("sensor_readings", sa.Column("longitude", sa.Float()))
    op.create_index("ix_sensor_readings_location_name", "sensor_readings", ["location_name"])
    op.create_index("ix_sensor_readings_latitude", "sensor_readings", ["latitude"])
    op.create_index("ix_sensor_readings_longitude", "sensor_readings", ["longitude"])


def downgrade():
    op.drop_index("ix_sensor_readings_longitude", table_name="sensor_readings")
    op.drop_index("ix_sensor_readings_latitude", table_name="sensor_readings")
    op.drop_index("ix_sensor_readings_location_name", table_name="sensor_readings")
    op.drop_column("sensor_readings", "longitude")
    op.drop_column("sensor_readings", "latitude")
    op.drop_column("sensor_readings", "location_name")
    op.drop_column("sensor_readings", "dust_particle_size")
