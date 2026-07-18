from __future__ import annotations

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from web.db.models import Base

_WORKBENCH_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_FILE = _WORKBENCH_ROOT / 'workbench.db'

_engine = create_engine(
    f'sqlite:///{_DB_FILE}',
    connect_args={'check_same_thread': False},
)
_Session = sessionmaker(bind=_engine, autoflush=False)


def init_db():
    Base.metadata.create_all(_engine)
    _migrate()


def _migrate():
    from sqlalchemy import text, inspect
    inspector = inspect(_engine)
    existing = {c['name'] for c in inspector.get_columns('calculations')}
    with _engine.connect() as conn:
        if 'error_message' not in existing:
            conn.execute(text("ALTER TABLE calculations ADD COLUMN error_message TEXT DEFAULT ''"))
            conn.commit()


def get_session():
    return _Session()
