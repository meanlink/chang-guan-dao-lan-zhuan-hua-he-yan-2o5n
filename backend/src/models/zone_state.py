from sqlalchemy import Double, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class DatasetZoneState(Base):
    """Currently visible rule version for one dataset. Missing row means the base identity version."""
    __tablename__ = 'dataset_zone_states'
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'), unique=True, index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey('zone_rule_versions.id'))
    updated_at: Mapped[float] = mapped_column(Double)


class ZoneRuleDatasetLock(Base):
    """One in-flight recompute per dataset; the unique key serialises overlapping switches."""
    __tablename__ = 'zone_rule_dataset_locks'
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'), primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey('zone_rule_versions.id'), index=True)
    created_at: Mapped[float] = mapped_column(Double)
