"""The same malformed inputs must never be coerced or persisted by any route."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import app as pm
from test_support import seed_legacy_demo


class ValidationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = patch.multiple(pm, DATA_DIR=directory.name,
                                  DB_FILE=str(Path(directory.name) / 'db.json'))
        settings.start(); self.addCleanup(settings.stop)
        seed_legacy_demo(pm)
        self.client = pm.app.test_client()
        self.base = '/api/projects/demo-migration'
        self.project = self.client.get(self.base).get_json()['project']
        self.original = Path(pm.DB_FILE).read_bytes()
        self.model = patch.object(pm.ai_service, 'generate', side_effect=AssertionError('Invalid input reached AI'))
        self.model.start(); self.addCleanup(self.model.stop)

    def reject(self, path, body, method='post', status=400):
        response = getattr(self.client, method)(path, json=body)
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.assertIsInstance(response.get_json()['error'], str)
        self.assertEqual(Path(pm.DB_FILE).read_bytes(), self.original)

    def test_top_level_types_and_malformed_json(self):
        routes = [('post','/api/projects'),('put',self.base)] + [
            ('post',self.base+suffix) for suffix in ['/impact','/impact/explanation','/simulate',
                '/checklist','/apply-checklist','/sandbox','/sandbox/apply','/assistant']]
        for method, path in routes:
            for body in [[], 'text', 7, True]:
                with self.subTest(path=path, body=body): self.reject(path, body, method)
            for raw in ['null','{"broken":', '']:
                response = getattr(self.client, method)(path, data=raw, content_type='application/json')
                self.assertEqual(response.status_code, 400)
                self.assertIsInstance(response.get_json()['error'], str)
                self.assertEqual(Path(pm.DB_FILE).read_bytes(), self.original)

    def test_invalid_task_fields_across_creation_update_impact_and_checklist(self):
        bad_fields = {'name':[None,False,[],{},'', 'x'*201], 'owner':[None,False,[],{},'x'*121],
            'duration':[None,True,'3',1.5,-1,100001], 'start_delay':[None,False,'2',-1],
            'status':[None,True,[],{},'unknown'], 'dependencies':[None,'backend',{},[None],[False],[{}],['missing']]}
        for field, values in bad_fields.items():
            for value in values:
                task = {'id':'new','name':'Task','duration':3,'dependencies':[],field:value}
                changed = copy.deepcopy(self.project['tasks']); changed[3][field] = value
                calls = [('post','/api/projects',{'tasks':[task]}),
                    ('put',self.base,{'tasks':changed}),
                    ('post',self.base+'/impact',{'task_id':'backend','changes':{field:value},'apply':True}),
                    ('post',self.base+'/apply-checklist',{'subtasks':[task]})]
                calls.append(('post',self.base+'/checklist',task))
                for method,path,body in calls:
                    with self.subTest(field=field,value=value,path=path): self.reject(path,body,method)

    def test_nested_tasks_and_subtasks_are_objects(self):
        for values in [None, {}, 'tasks', [None], [[]], [True], ['task']]:
            self.reject('/api/projects', {'tasks':values})
            self.reject(self.base, {'tasks':values}, 'put')
            self.reject(self.base+'/impact', {'task_id':'backend','tasks':values,'apply':True})
            self.reject(self.base+'/apply-checklist', {'subtasks':values})

    def test_apply_and_explain_require_real_boolean(self):
        for value in ['false','true',0,1,None,[],{}]:
            self.reject(self.base+'/impact', {'task_id':'backend','changes':{'duration':17},'apply':value})
            self.reject(self.base+'/sandbox', {'shifts':{'backend':3},'explain':value})
            self.reject(self.base+'/simulate', {'changes':{'backend':{'set_done':value}}})

    def test_delta_rejects_invalid_types_out_of_range_and_conflicting_fields(self):
        for delta in [None, True, '3', [], {}, 1.5, -11, 100001, 100000]:
            self.reject(self.base+'/impact', {'task_id':'backend','changes':{'duration_delta':delta},'apply':True})
            self.reject(self.base+'/simulate', {'changes':{'backend':{'duration':delta}}})
        self.reject(self.base+'/impact', {'task_id':'backend','changes':{'duration':5,'duration_delta':3},'apply':True})

    def test_project_text_deadline_and_revision_types(self):
        for body in [{'name':None},{'name':[]},{'name':'x'*201},{'name':''},
                     {'description':{}},{'description':'x'*4001},{'deadline':{}},{'deadline':[]},
                     {'deadline':'30'},{'deadline':False}]:
            self.reject('/api/projects', body)
            self.reject(self.base, body, 'put')
        for revision in [None,False,[],{},'']:
            self.reject(self.base, {'base_revision':revision}, 'put')
            self.reject(self.base+'/impact', {'task_id':'backend','base_revision':revision,'apply':True})

    def test_unknown_fields_and_invalid_identifiers(self):
        for path in ['/api/projects',self.base+'/impact',self.base+'/simulate',self.base+'/checklist',
                     self.base+'/apply-checklist',self.base+'/sandbox',self.base+'/impact/explanation']:
            self.reject(path, {'unsupported':True})
        self.reject(self.base+'/impact', {'task_id':'backend','changes':{'unsupported':2}})
        for value in [None,True,[],{},'']:
            self.reject('/api/projects', {'tasks':[{'id':value,'name':'Task'}]})
            self.reject(self.base+'/impact', {'task_id':value})
            self.reject(self.base+'/impact/explanation', {'explanation_id':value})
        self.reject(self.base+'/impact', {'task_id':'backend','changes':{'id':'another'}})
        self.reject(self.base+'/impact', {'task_id':'missing'}, status=404)

    def test_scenario_nested_shapes_and_unknown_tasks(self):
        for changes in [None, [], {'backend':None}, {'backend':[]}, {'backend':{'unknown':3}}, {'missing':{'duration':2}}]:
            self.reject(self.base+'/simulate', {'changes':changes})
        for shifts in [None, [], {'backend':None}, {'backend':'3'}, {'backend':True}, {'missing':2}]:
            self.reject(self.base+'/sandbox', {'shifts':shifts,'explain':False})
        self.reject(self.base+'/sandbox', {'shifts':{},'task_id':'backend','shift_days':2})

    def test_valid_zero_and_signed_delta_preserve_preview_and_save_contract(self):
        for delta in [0, -10, 5]:
            response = self.client.post(self.base+'/impact', json={
                'task_id':'backend','changes':{'duration_delta':delta},'apply':False})
            self.assertEqual(response.status_code,200)
            task = next(t for t in response.get_json()['after']['tasks'] if t['id']=='backend')
            self.assertEqual(task['duration'],10+delta)
            self.assertEqual(Path(pm.DB_FILE).read_bytes(),self.original)
        response = self.client.post(self.base+'/impact', json={
            'task_id':'backend','changes':{'duration':0},'apply':True})
        self.assertTrue(response.get_json()['applied'])
        self.assertEqual(self.client.get(self.base).get_json()['project']['tasks'][3]['duration'],0)
