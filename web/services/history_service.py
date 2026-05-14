"""Helpers for the dashboard calculation history: filtering and deletion."""
from __future__ import annotations

import os
import shutil

from web.db.database import get_session
from web.db.models import Calculation


def filter_rows(rows, mode: str = 'All', project: str = 'All', search: str = ''):
    """Return rows filtered by mode, project, and a case-insensitive substring search
    across model / memo / project / status fields."""
    q = (search or '').strip().lower()
    out = []
    for r in rows:
        if mode != 'All' and r.get('mode') != mode:
            continue
        if project != 'All' and r.get('project') != project:
            continue
        if q:
            hay = f"{r.get('model','')} {r.get('memo','')} {r.get('project','')} {r.get('status','')}".lower()
            if q not in hay:
                continue
        out.append(r)
    return out


def delete_calculations(ids):
    """Delete DB records and on-disk result directories for the given calculation IDs.

    Returns (deleted_count, errors). Errors list non-fatal rmtree failures; the DB
    row is still deleted in that case to avoid orphaned history entries.
    """
    errors: list[str] = []
    deleted = 0
    session = get_session()
    try:
        for cid in ids:
            calc = session.query(Calculation).filter_by(id=cid).first()
            if calc is None:
                continue
            rdir = calc.result_dir or ''
            if rdir and os.path.isdir(rdir):
                try:
                    shutil.rmtree(rdir)
                except Exception as e:
                    errors.append(f'id={cid}: rmtree failed: {e}')
            session.delete(calc)
            deleted += 1
        session.commit()
    finally:
        session.close()
    return deleted, errors
