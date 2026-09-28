"""Exercise project storage and validation with an isolated database and no network."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import app as pm
from test_support import seed_legacy_demo


class ProjectIntegrityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        settings = patch.multiple(pm, DATA_DIR=temp.name, DB_FILE=str(Path(temp.name) / 'db.json'))
        settings.start(); self.addCleanup(settings.stop)
        offline = patch.dict(os.environ, {'PM_RADAR_AI_DISABLED':'1'})
        offline.start(); self.addCleanup(offline.stop)
        seed_legacy_demo(pm)
        self.client = pm.app.test_client()
        self.base = '/api/projects/demo-migration'
        self.original = self.client.get(self.base).get_json()

    def test_bad_graph_cannot_be_saved_during_creation_or_update(self):
        task = lambda id, deps: dict(id=id, name=id, duration=2, dependencies=deps)
        cases = [[task('a',['b']),task('b',['a'])],
                 [task('a',['a'])], [task('a',['missing'])],
                 [task('a',[]),task('a',[])]]
        saved = Path(pm.DB_FILE).read_bytes()
        for tasks in cases:
            for method,path in [('post','/api/projects'),('put',self.base)]:
                response = getattr(self.client, method)(path, json={'name':'Test','tasks':tasks})
                self.assertIn(response.status_code,[400,409])
                self.assertEqual(Path(pm.DB_FILE).read_bytes(),saved)

    def test_invalid_input_is_reported_without_corrupting_database(self):
        saved = Path(pm.DB_FILE).read_bytes()
        for body in [[], {'tasks':{}}, {'tasks':[None]}, {'deadline':-5},
                     {'deadline':True}, {'deadline':1.5}, {'deadline':100001}]:
            response = self.client.put(self.base,json=body)
            self.assertEqual(response.status_code,400)
            self.assertIsInstance(response.get_json()['error'],str)
            self.assertEqual(Path(pm.DB_FILE).read_bytes(),saved)

    def test_edit_from_stale_form_cannot_overwrite_current_project(self):
        revision = self.original['revision']
        self.client.put(self.base,json={'name':'Updated'})
        saved = Path(pm.DB_FILE).read_bytes()
        bodies = [('put','',{'tasks':self.original['project']['tasks']}),
                  ('post','/impact',{'task_id':'backend','changes':{'duration':17},'apply':True})]
        for method,suffix,body in bodies:
            response = getattr(self.client,method)(self.base+suffix,json={**body,'base_revision':revision})
            self.assertEqual(response.status_code,409)
            self.assertEqual(response.get_json()['code'],'revision_conflict')
            self.assertEqual(Path(pm.DB_FILE).read_bytes(),saved)

    def test_full_project_lifecycle_and_empty_state(self):
        created = self.client.post('/api/projects',json={'name':'Проверка','deadline':12}).get_json()
        path = '/api/projects/' + created['project']['id']
        self.assertEqual(created['analysis']['summary']['project_duration'],0)
        tasks = [dict(id='one',name='Задача',duration=4,owner='Ольга',status='todo',dependencies=[])]
        updated = self.client.put(path,json={'tasks':tasks}).get_json()
        self.assertEqual(updated['analysis']['summary']['project_duration'],4)
        done = self.client.post(path+'/impact',json={'task_id':'one','changes':{'status':'done'},'apply':True}).get_json()
        self.assertEqual(done['after']['summary']['project_duration'],0)
        self.assertEqual(self.client.delete(path).status_code,200)
        self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.get(self.base).get_json(),self.original)


    def test_short_checklists_preserve_the_users_total_duration(self):
        for duration in range(8):
            response = self.client.post(self.base+'/checklist',json={'name':'Разработка API','duration':duration})
            self.assertEqual(response.status_code,200)
            proposal = response.get_json()['suggestion']
            self.assertEqual(proposal['original_duration'],duration)
            self.assertEqual(sum(task['duration'] for task in proposal['subtasks']),duration)

    def test_cyclic_impact_and_checklist_never_write(self):
        saved = Path(pm.DB_FILE).read_bytes()
        response = self.client.post(self.base+'/impact',json={
            'task_id':'design_ui','changes':{'dependencies':['deploy']},'apply':True})
        self.assertEqual(response.status_code,409)
        response = self.client.post(self.base+'/apply-checklist',json={'subtasks':[
            {'id':'a','name':'A','duration':1,'dependencies':['b']},
            {'id':'b','name':'B','duration':1,'dependencies':['a']}]})
        self.assertEqual(response.status_code,400)
        self.assertEqual(Path(pm.DB_FILE).read_bytes(),saved)
