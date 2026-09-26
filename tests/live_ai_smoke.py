"""Explicit opt-in integration check: uses OpenRouter credits, never user projects."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import app as pm
import ai_service

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Allow 5 real model requests on demo data')
    if not parser.parse_args().run:
        parser.error('Pass --run to permit real requests')
    if not ai_service.llm_available():
        raise SystemExit('AI is not configured')
    with tempfile.TemporaryDirectory() as directory, patch.multiple(pm,
            DATA_DIR=directory, DB_FILE=str(Path(directory) / 'db.json')):
        client = pm.app.test_client()
        root = '/api/projects/demo-migration'
        client.get(root)
        original = Path(pm.DB_FILE).read_bytes()
        scenarios = [
            ('sandbox', 'post', '/sandbox', {'task_id':'backend','shift_days':3}),
            ('impact', 'post', '/impact', {'task_id':'backend','changes':{'duration':17},'apply':False}),
            ('checklist', 'post', '/checklist', {'name':'Разработка API','duration':7}),
            ('report', 'get', '/report.md', None),
            ('missing_data', 'post', '/assistant', {'message':'Какой бюджет проекта? Кто из сотрудников сегодня на больничном?'}),
        ]
        for name, method, path, body in scenarios:
            response = getattr(client, method)(root+path, **({'json':body} if body else {}))
            assert response.status_code == 200, (name,response.status_code)
            data = response.get_json() if response.is_json else None
            used = data['llm'] if data else response.headers.get('X-AI-Source') == 'llm'
            text = (data.get('explanation') or data.get('reply') or data.get('text')) if data else response.get_data(as_text=True)
            print(json.dumps({'scenario':name,'llm':used,'model':data['ai']['model'] if data else response.headers.get('X-AI-Model'),
                              'reason':data['ai'].get('reason') if data else response.headers.get('X-AI-Reason'),
                              'text':text},ensure_ascii=False), flush=True)
            assert used, f'{name}: live model did not provide the answer'
            assert Path(pm.DB_FILE).read_bytes() == original, f'{name}: unexpected mutation'
            if name == 'sandbox':
                assert data['fact']['task_duration'] == 10 and data['fact']['duration_delta'] == 3
            if name == 'checklist':
                assert sum(t['duration'] for t in data['suggestion']['subtasks']) == 7
        print('PASS: 5 live scenarios; demo DB unchanged.', flush=True)

if __name__ == '__main__': main()
