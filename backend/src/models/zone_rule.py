from sqlalchemy import String, JSON, Double, ForeignKey, Integer, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class ZoneRuleVersion(Base):
    """A frozen zone rename/merge rule set that can be recomputed and switched atomically."""
    __tablename__ = 'zone_rule_versions'
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    note: Mapped[str] = mapped_column(String(500), default='')
    rules: Mapped[list] = mapped_column(JSON, default=list)
    # ready | blocked | building | active | failed | superseded | rolled_back
    status: Mapped[str] = mapped_column(String(20), default='ready', index=True)
    error: Mapped[str] = mapped_column(String(2000), default='')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    started_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    activated_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    superseded_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class ZoneRuleBatch(Base):
    """Per-batch recompute progress for one rule version."""
    __tablename__ = 'zone_rule_batches'
    __table_args__ = (UniqueConstraint('version_id', 'dataset_id', name='uq_zone_batch'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey('zone_rule_versions.id'), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'), index=True)
    # pending | running | completed | failed | blocked
    status: Mapped[str] = mapped_column(String(20), default='pending')
    total_jobs: Mapped[int] = mapped_column(Integer, default=0)
    done_jobs: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(2000), default='')
    error: Mapped[str] = mapped_column(String(2000), default='')
    previous_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class ZoneRuleStage(Base):
    """Staged (not yet visible) job result computed under a rule version."""
    __tablename__ = 'zone_rule_stages'
    __table_args__ = (UniqueConstraint('version_id', 'job_id', name='uq_zone_stage'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey('zone_rule_versions.id'), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'), index=True)
    # pending | completed | failed
    status: Mapped[str] = mapped_column(String(20), default='pending')
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(2000), default='')
    updated_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class ZoneRuleSnapshot(Base):
    """Previous visible job state, kept so an activated version can be rolled back exactly."""
    __tablename__ = 'zone_rule_snapshots'
    __table_args__ = (UniqueConstraint('version_id', 'job_id', name='uq_zone_snapshot'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey('zone_rule_versions.id'), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'), index=True)
    previous_zone_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_params: Mapped[dict] = mapped_column(JSON, default=dict)
    previous_result: Mapped[dict] = mapped_column(JSON, default=dict)
    previous_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    previous_status: Mapped[str] = mapped_column(String(20), default='completed')
    previous_error: Mapped[str] = mapped_column(String(2000), default='')
