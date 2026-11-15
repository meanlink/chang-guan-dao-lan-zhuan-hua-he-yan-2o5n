from sqlalchemy import String, Double, ForeignKey, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Report(Base):
    __tablename__ = 'reports'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    destination: Mapped[str] = mapped_column(String(120))
    interval_seconds: Mapped[int]
    next_run: Mapped[float] = mapped_column(Double)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Rule version captured when the plan was created; delivery stays inside it.
    zone_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Set when the plan can no longer deliver the version it was approved under.
    blocked_reason: Mapped[str] = mapped_column(String(500), default='')
class Delivery(Base):
    __tablename__ = 'deliveries'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    created_at: Mapped[float] = mapped_column(Double)
    checksum: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(160))
    destination: Mapped[str] = mapped_column(String(120))
    # Frozen identity of what this archive contains; never rewritten by later switches.
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    params_checksum: Mapped[str] = mapped_column(String(64), default='')
