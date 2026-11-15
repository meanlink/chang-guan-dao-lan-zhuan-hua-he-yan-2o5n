from src.config.database import Base, engine
from src import models

# Columns added to pre-existing tables. PostgreSQL gets ADD COLUMN guarded by
# an inspector check; the same path works for SQLite used in local dev.
_NEW_COLUMNS = {
    'jobs': [
        ('zone_version_id', 'INTEGER'), ('zone_version', 'INTEGER'),
    ],
    'reports': [
        ('zone_version_id', 'INTEGER'), ('zone_version', 'INTEGER'),
        ('blocked_reason', "VARCHAR(500) NOT NULL DEFAULT ''"),
    ],
    'deliveries': [
        ('job_id', 'INTEGER'), ('zone_version_id', 'INTEGER'), ('zone_version', 'INTEGER'),
        ('params_checksum', "VARCHAR(64) NOT NULL DEFAULT ''"),
    ],
}


def migrate():
    Base.metadata.create_all(engine)
    from sqlalchemy import inspect
    with engine.begin() as conn:
        inspector = inspect(conn)
        existing_tables = set(inspector.get_table_names())
        for table, columns in _NEW_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {c['name'] for c in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in present:
                    conn.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')


if __name__ == '__main__':
    migrate()
