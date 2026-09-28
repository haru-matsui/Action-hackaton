import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import assistant
import app as pm
from schedule import analyze


class ScenarioQuestionTests(unittest.TestCase):
    def setUp(self):
        self.project = {'name':'Проверка','deadline':30,'tasks':[
            dict(id='a',name='Разработка',duration=10,status='todo',owner='',dependencies=[]),
            dict(id='b',name='Тестирование',duration=5,status='todo',owner='',dependencies=['a'])]}

    def ask(self, text, project=None):
        project = project or self.project
        original = copy.deepcopy(project)
        answer, facts = assistant.chat(text, project, analyze(project['tasks'],project['deadline']))
        self.assertEqual(project,original)
        return answer, facts

    def test_direction_and_explicit_units(self):
        cases = [('завершится на 5 дней раньше',10),('задержится на 5 дней',20),
                 ('ускорится на три дня',12),('задержится на две недели',25),
                 ('задержится на неделю',20),('завершится раньше на день',14),
                 ('закроем на 3 дня раньше',12),('задержится на 1 рабочий день',16)]
        for phrase, expected in cases:
            with self.subTest(phrase=phrase):
                _,facts=self.ask('Что будет, если Разработка '+phrase+'?')
                self.assertEqual(facts['after_summary']['project_duration'],expected)
                self.assertFalse(facts['saved'])

    def test_missing_ambiguous_or_invalid_quantity_never_simulates(self):
        for phrase in ['задержится','задержится на 1.5 дня','задержится на -3 дня',
                       'задержится на - 3 дня','задержится на 3 или 5 дней',
                       'задержится от 3 до 5 дней','не задержится на 3 дня',
                       'задержится и ускорится на 3 дня','сдвинется на 3 дня',
                       'задержится на 3 дня и 2 недели','ускорится на 20 дней',
                       'задержится на 100001 день','ускорится на двадцать один день',
                       'задержится на пятьдесят три дня','задержится на неделю и на день',
                       'получит нового ответственного']:
            with self.subTest(phrase=phrase):
                _,facts=self.ask('Что будет, если Разработка '+phrase+'?')
                self.assertEqual(facts['type'],'insufficient_data')
                self.assertNotIn('simulation',facts)

    def test_zero_completion_and_lower_boundary(self):
        _,facts=self.ask('Что будет, если Разработка задержится на 0 дней?')
        self.assertEqual(facts['type'],'unchanged')
        _,facts=self.ask('Что будет, если Разработка завершится на 10 дней раньше?')
        self.assertEqual(facts['after_summary']['project_duration'],5)
        _,facts=self.ask('Что будет, если Разработка будет выполнена?')
        self.assertEqual(facts['simulation'],{'a':{'set_done':True}})
        self.project['tasks'][0]['status']='done'
        _,facts=self.ask('Что будет, если Разработка задержится на 3 дня?')
        self.assertEqual(facts['type'],'insufficient_data')

    def test_duplicate_and_multiple_task_names_require_clarification(self):
        for names,question in [(['Разработка','Разработка'],'Разработка'),
                               (['Разработка backend','Разработка frontend'],'Разработка'),
                               (['Разработка','Тестирование'],'Разработка и Тестирование')]:
            project=copy.deepcopy(self.project)
            for task,name in zip(project['tasks'],names): task['name']=name
            _,facts=self.ask(f'Что будет, если {question} задержится на 3 дня?',project)
            self.assertEqual(facts['type'],'insufficient_data')

    def test_long_full_name_and_numbers_inside_name_are_not_scenario_values(self):
        project=copy.deepcopy(self.project)
        project['tasks'][1]['name']='Разработка версии 5 дней'
        _,facts=self.ask('Что будет, если Разработка версии 5 дней задержится на 3 дня?',project)
        self.assertEqual(facts['simulation'],{'b':{'duration':3}})

    def test_api_clarification_never_calls_model_or_changes_database(self):
        with tempfile.TemporaryDirectory() as d, patch.multiple(pm,DATA_DIR=d,DB_FILE=str(Path(d)/'db.json')):
            pm.save_db({'projects':{'p':{**self.project,'id':'p'}}})
            original=Path(pm.DB_FILE).read_bytes()
            with patch.object(pm.ai_service,'generate') as model:
                response=pm.app.test_client().post('/api/projects/p/assistant',json={
                    'message':'Что будет, если Разработка задержится?'})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.get_json()['facts']['type'],'insufficient_data')
                self.assertFalse(response.get_json()['llm'])
                model.assert_not_called()
            self.assertEqual(Path(pm.DB_FILE).read_bytes(),original)
