"""Regression checks for the core demo and impact preview flow."""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))
import app as pm_app


class ApiFlowTest(unittest.TestCase):
    def setUp(self):
        self.no_network = patch.dict(os.environ, {'PM_RADAR_AI_DISABLED': '1'})
        self.no_network.start()
        self.temp = tempfile.TemporaryDirectory()
        pm_app.DATA_DIR = self.temp.name
        pm_app.DB_FILE = os.path.join(self.temp.name, 'db.json')
        self.client = pm_app.app.test_client()

    def tearDown(self):
        self.no_network.stop()
        self.temp.cleanup()

    def test_demo_preview_and_new_task(self):
        for path in ('/', '/static/css/app.css', '/static/js/app.js',
                     '/static/js/api.js', '/static/js/ui.js', '/static/js/views.js'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            response.close()

        demo = self.client.get('/api/projects/demo-migration').get_json()
        self.assertEqual(len(demo['project']['tasks']), 10)
        self.assertEqual(demo['analysis']['summary']['project_duration'], 29)

        preview = self.client.post('/api/projects/demo-migration/impact', json={
            'task_id': 'backend', 'changes': {'duration': 17}, 'apply': False,
        }).get_json()
        self.assertEqual(preview['diff']['duration_delta'], 7)
        self.assertTrue(preview['after']['summary']['deadline_breached'])
        self.assertEqual(self.client.get('/api/projects/demo-migration').get_json()
                         ['project']['tasks'][3]['duration'], 10)

        new_task = {'id': 'new-task', 'name': 'Новая задача', 'duration': 5,
                    'owner': 'Анна Смирнова', 'status': 'todo', 'dependencies': ['deploy']}
        body = {'task_id': new_task['id'], 'changes': new_task, 'apply': False,
                'tasks': demo['project']['tasks'] + [new_task]}
        added = self.client.post('/api/projects/demo-migration/impact', json=body).get_json()
        self.assertEqual(added['before']['summary']['project_duration'], 29)
        self.assertEqual(added['after']['summary']['project_duration'], 34)
        self.assertEqual(added['diff']['duration_delta'], 5)
        self.assertEqual(len(self.client.get('/api/projects/demo-migration').get_json()
                             ['project']['tasks']), 10)

        body['apply'] = True
        applied = self.client.post('/api/projects/demo-migration/impact', json=body).get_json()
        self.assertTrue(applied['applied'])
        self.assertEqual(len(self.client.get('/api/projects/demo-migration').get_json()
                             ['project']['tasks']), 11)


if __name__ == '__main__':
    unittest.main()
