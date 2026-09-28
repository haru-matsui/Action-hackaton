"""Impact writes and previews do not depend on the language model."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import app as pm
from test_support import seed_legacy_demo


class ImpactTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = patch.multiple(pm, DATA_DIR=directory.name,
                                  DB_FILE=str(Path(directory.name) / 'db.json'))
        settings.start(); self.addCleanup(settings.stop)
        seed_legacy_demo(pm)
        self.client = pm.app.test_client()
        self.base = '/api/projects/demo-migration'
        self.revision = self.client.get(self.base).get_json()['revision']
        pm._impact_receipts.clear()
        self.result = {'text':'Пояснение', 'llm':True, 'ai':{'source':'llm'}}

    def impact(self, apply=False, duration=17):
        return self.client.post(self.base+'/impact', json={'task_id':'backend',
            'changes':{'duration':duration}, 'apply':apply, 'base_revision':self.revision})

    def explain(self, data, base=None):
        return self.client.post((base or self.base)+'/impact/explanation',
                                json={'explanation_id':data['explanation_id']})

    def test_preview_and_save_return_without_calling_model(self):
        original = Path(pm.DB_FILE).read_bytes()
        with patch.object(pm.ai_service, 'generate', side_effect=AssertionError('must not wait')) as model:
            preview = self.impact().get_json()
            self.assertEqual(preview['diff']['new_duration'], 36)
            self.assertEqual(Path(pm.DB_FILE).read_bytes(), original)
            saved = self.impact(True).get_json()
            self.assertTrue(saved['applied'])
            self.assertNotEqual(saved['result_revision'], self.revision)
            self.assertEqual(self.client.get(self.base).get_json()['analysis']['summary']['project_duration'], 36)
            model.assert_not_called()
        self.assertEqual(self.impact(True).status_code, 409)  # replay cannot write twice

    def test_exact_snapshot_is_interpreted_without_writing(self):
        data = self.impact(True).get_json()
        original = Path(pm.DB_FILE).read_bytes()
        with patch.object(pm.ai_service, 'generate', return_value=self.result) as model:
            response = self.explain(data)
            self.assertEqual(response.status_code, 200)
            facts = model.call_args.args[0]
            self.assertTrue(facts['saved'])
            self.assertEqual(facts['diff']['duration_delta'], 7)
            self.assertEqual(facts['before']['summary']['project_duration'], 29)
            self.assertEqual(facts['summary']['project_duration'], 36)
        self.assertEqual(response.get_json()['result_revision'], data['result_revision'])
        self.assertEqual(Path(pm.DB_FILE).read_bytes(), original)

    def test_stale_snapshot_rejected_before_model(self):
        data = self.impact().get_json()
        self.impact(True)
        with patch.object(pm.ai_service, 'generate') as model:
            self.assertEqual(self.explain(data).status_code, 409)
            model.assert_not_called()

    def test_edit_during_generation_discards_response(self):
        data = self.impact().get_json()
        def generate(*args):
            self.impact(True)
            return self.result
        with patch.object(pm.ai_service, 'generate', side_effect=generate):
            response = self.explain(data)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['code'], 'revision_conflict')

    def test_expired_wrong_project_and_missing_receipts_do_not_call_model(self):
        data = self.impact().get_json()
        with patch.object(pm.ai_service, 'generate') as model:
            self.assertEqual(self.explain(data, '/api/projects/other').status_code, 410)
            self.assertEqual(self.explain({'explanation_id':'unknown'}).status_code, 410)
            with patch.object(pm.time, 'monotonic', return_value=pm.time.monotonic()+pm.IMPACT_TTL+1):
                self.assertEqual(self.explain(data).status_code, 410)
            model.assert_not_called()

    def test_unavailable_model_keeps_saved_plan_and_calculated_summary(self):
        data = self.impact(True).get_json()
        original = Path(pm.DB_FILE).read_bytes()
        with patch.object(pm.ai_service, 'generate', return_value={
                'text':data['explanation'], 'llm':False, 'ai':{'source':'rules','reason':'timeout'}}):
            response = self.explain(data).get_json()
        self.assertFalse(response['llm'])
        self.assertEqual(response['explanation'], data['explanation'])
        self.assertEqual(Path(pm.DB_FILE).read_bytes(), original)

    def test_receipts_are_bounded(self):
        with patch.object(pm, 'IMPACT_LIMIT', 2):
            first = self.impact().get_json()
            self.impact(); self.impact()
        self.assertEqual(len(pm._impact_receipts), 2)
        self.assertEqual(self.explain(first).status_code, 410)
