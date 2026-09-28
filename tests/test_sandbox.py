"""Scenario consistency, validation and optimistic writes; no real model calls."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import app as pm
from test_support import seed_legacy_demo
import ai_service


class SandboxTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        settings = patch.multiple(pm, DATA_DIR=temp.name, DB_FILE=str(Path(temp.name) / 'db.json'))
        settings.start(); self.addCleanup(settings.stop)
        offline = patch.dict(os.environ, {'PM_RADAR_AI_DISABLED': '1'})
        offline.start(); self.addCleanup(offline.stop)
        seed_legacy_demo(pm)
        self.client = pm.app.test_client()
        self.base = '/api/projects/demo-migration'
        self.original = self.client.get(self.base).get_json()
        self.revision = self.original['revision']

    def preview(self, shifts, **extra):
        return self.client.post(self.base + '/sandbox', json={
            'shifts': shifts, 'base_revision': self.revision, 'explain': False, **extra})

    def apply(self, data, **extra):
        return self.client.post(self.base + '/sandbox/apply', json={
            'shifts': data['shifts'], 'base_revision': data['base_revision'],
            'scenario_key': data['scenario_key'], **extra})

    def test_multiple_changes_propagate_and_save_exact_preview_without_ai(self):
        original_bytes = Path(pm.DB_FILE).read_bytes()
        with patch.object(ai_service, 'generate') as model:
            data = self.preview({'backend': 3, 'integration': 2}).get_json()
            by_id = {t['id']: t for t in data['after']['tasks']}
            self.assertEqual(by_id['backend']['early_start'], 9)
            self.assertEqual(by_id['integration']['early_start'], 21)
            self.assertEqual(by_id['testing']['early_start'], 24)
            self.assertEqual(data['after_summary']['project_duration'], 34)
            changes = {change['task_id']: change for change in data['changes']}
            self.assertEqual(changes['integration']['wait_change_days'], 2)
            self.assertEqual(changes['integration']['start_shift_days'], 5)
            self.assertEqual(changes['integration']['shift'], 5)
            self.assertEqual(data['after_summary']['project_deadline'], 30)
            self.assertEqual(original_bytes, Path(pm.DB_FILE).read_bytes())
            saved = self.apply(data).get_json()
            self.assertEqual(saved['analysis'], data['after'])
            self.assertNotEqual(saved['revision'], self.revision)
            model.assert_not_called()
        original = {t['id']: t for t in self.original['project']['tasks']}
        for task in saved['project']['tasks']:
            self.assertEqual(task['duration'], original[task['id']]['duration'])
            self.assertEqual(task['dependencies'], original[task['id']]['dependencies'])

    def test_changed_project_rejects_preview_explanation_and_apply_without_overwrite(self):
        data = self.preview({'backend': 3}).get_json()
        self.client.put(self.base, json={'name': 'Другой участник изменил проект'})
        current = Path(pm.DB_FILE).read_bytes()
        for response in [self.preview({'backend': 3}), self.preview({'backend': 3}, explain=True), self.apply(data)]:
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.get_json()['code'], 'revision_conflict')
        self.assertEqual(current, Path(pm.DB_FILE).read_bytes())

    def test_apply_is_not_repeatable_and_requires_the_calculated_scenario(self):
        data = self.preview({'backend': 3}).get_json()
        self.assertEqual(self.apply(data, shifts={'backend': 4}).status_code, 409)
        self.assertEqual(self.client.post(self.base + '/sandbox/apply', json={'shifts': {'backend': 3}}).status_code, 400)
        self.assertEqual(self.apply(data).status_code, 200)
        saved = Path(pm.DB_FILE).read_bytes()
        self.assertEqual(self.apply(data).status_code, 409)
        self.assertEqual(saved, Path(pm.DB_FILE).read_bytes())

    def test_invalid_shifts_and_started_tasks_never_change_project(self):
        original = Path(pm.DB_FILE).read_bytes()
        cases = [{'backend': -1}, {'backend': 1.5}, {'backend': True}, {'backend': '3'},
                 {'backend': 100001}, {'missing': 2}, {'analysis': 2}, {'design_ui': 2}, [], None]
        for shifts in cases:
            with self.subTest(shifts=shifts):
                self.assertEqual(self.preview(shifts).status_code, 400)
        self.assertEqual(original, Path(pm.DB_FILE).read_bytes())

    def test_no_change_skips_model_and_missing_deadline_is_not_low_risk(self):
        with patch.object(ai_service, 'generate') as model:
            data = self.preview({'backend': 0}, explain=True).get_json()
            self.assertEqual(data['changes'], [])
            model.assert_not_called()
        self.client.put(self.base, json={'deadline': None})
        self.revision = self.client.get(self.base).get_json()['revision']
        data = self.preview({'backend': 3}).get_json()
        self.assertIsNone(data['fact']['slack_left'])
        self.assertEqual(data['fact']['risk'], 'не определён')
        self.assertEqual(data['fact']['deadline_shift'], 0)

    def test_explanation_uses_same_scenario_and_detects_change_during_model_call(self):
        result = {'text': 'Пояснение сценария', 'llm': True, 'ai': {'source': 'llm'}}
        data = self.preview({'backend': 3, 'frontend': 1}).get_json()
        with patch.object(ai_service, 'generate', return_value=result) as model:
            explained = self.preview({'frontend': 1, 'backend': 3}, explain=True).get_json()
            self.assertEqual(data['scenario_key'], explained['scenario_key'])
            self.assertEqual(data['after'], explained['after'])
            facts = model.call_args.args[0]
            self.assertFalse(facts['saved'])
            self.assertEqual(len(facts['changes']), 2)
            self.assertEqual(facts['summary'], data['after_summary'])
        def concurrently_edit(*args, **kwargs):
            self.client.put(self.base, json={'deadline': 40})
            return result
        with patch.object(ai_service, 'generate', side_effect=concurrently_edit):
            self.assertEqual(self.preview({'backend': 3}, explain=True).status_code, 409)

    def test_existing_delay_can_be_reduced_and_zero_returns_original_plan(self):
        data = self.preview({'backend': 4}).get_json()
        self.apply(data)
        self.revision = self.client.get(self.base).get_json()['revision']
        earlier = self.preview({'backend': -4}).get_json()
        self.assertEqual(earlier['after_summary']['project_duration'], 29)
        self.assertEqual(self.preview({'backend': -5}).status_code, 400)
        no_change = self.preview({}).get_json()
        self.assertEqual(no_change['before'], no_change['after'])

    def test_dependency_propagation_cannot_move_already_started_work(self):
        for status in ['done', 'in_progress']:
            self.client.put(self.base, json={'tasks': [
                {'id': 'a', 'name': 'Подготовка', 'duration': 3, 'dependencies': [], 'status': 'todo'},
                {'id': 'b', 'name': 'Работа', 'duration': 2, 'dependencies': ['a'], 'status': status}]})
            self.revision = self.client.get(self.base).get_json()['revision']
            unchanged = Path(pm.DB_FILE).read_bytes()
            response = self.preview({'a': 2})
            self.assertEqual(response.status_code, 400)
            self.assertIn('Проверьте её зависимости', response.get_json()['error'])
            self.assertEqual(unchanged, Path(pm.DB_FILE).read_bytes())


if __name__ == '__main__':
    unittest.main()
