"""Explicit pre-calendar fixture for regression tests of legacy saved projects."""
import json
from pathlib import Path


def seed_legacy_demo(app):
    project = app.demo_project()
    project.pop('start_date', None)
    project.pop('deadline_date', None)
    project['deadline'] = 30
    Path(app.DB_FILE).write_text(json.dumps({'projects':{project['id']:project}},ensure_ascii=False),encoding='utf-8')
