"""Offline safety and integration tests. No real credentials or API charges."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import ai_service
import app as pm
from test_support import seed_legacy_demo
import assistant
from schedule import analyze, simulate, diff_analysis

def completion(value, **extra):
    return io.BytesIO(json.dumps({'model': ai_service.DEFAULT_MODEL, 'choices': [{
        'finish_reason': 'stop', 'message': {'content': json.dumps(value, ensure_ascii=False)},
        **extra}]}).encode())

class AdapterTests(unittest.TestCase):
    def setUp(self):
        ai_service._cache.clear()
        self.settings = patch.object(ai_service, 'config', return_value={
            'api_key': 'test-key', 'model': ai_service.DEFAULT_MODEL,
            'base_url': ai_service.DEFAULT_BASE, 'disabled': False})
        self.config_mock = self.settings.start()
        self.addCleanup(self.settings.stop)
        self.facts = {'mode': 'sandbox', 'shift': 3, 'deadline_shift': 2, 'saved': False}

    def test_real_request_contract_and_cache(self):
        with patch('urllib.request.urlopen', return_value=completion({'text':'Прогноз сдвинется на 2 дня.'})) as network:
            result = ai_service.generate(self.facts, 'Объясни', 'Резерв')
            self.assertTrue(result['llm'])
            req = network.call_args.args[0]
            body = json.loads(req.data)
            self.assertEqual(req.full_url, 'https://openrouter.ai/api/v1/chat/completions')
            self.assertEqual(req.get_header('Authorization'), 'Bearer test-key')
            self.assertEqual(body['model'], 'deepseek/deepseek-v4.1-flash')
            self.assertNotIn('tools', body)
            self.assertTrue(body['response_format']['json_schema']['strict'])
            self.assertEqual(json.loads(body['messages'][1]['content'])['facts'], self.facts)
            self.assertNotIn('test-key', json.dumps(body))
            self.assertTrue(ai_service.generate(self.facts, 'Объясни', 'Резерв')['ai']['cached'])
            self.assertEqual(network.call_count, 1)

    def test_unknown_numbers_rejected(self):
        with patch('urllib.request.urlopen', return_value=completion({'text':'Бюджет составит 999999 рублей.'})):
            result = ai_service.generate(self.facts, 'Бюджет?', 'Нет данных')
        self.assertFalse(result['llm'])
        self.assertEqual(result['text'], 'Нет данных')
        self.assertEqual(result['ai']['reason'], 'invalid_response')

    def test_calendar_dates_may_be_formatted_but_not_invented(self):
        facts = {'today':'2026-09-25','finish':'2026-10-28','duration':24}
        for text, accepted in [('Прогноз — 28.10.2026. Осталось 24 дня.',True),
                               ('Прогноз — 2026-10-28.',True),
                               ('Прогноз — 25.10.2026.',False),
                               ('Прогноз — 31.02.2026.',False),
                               ('Прогноз — 28.10.2026, осталось 999 дней.',False)]:
            with self.subTest(text=text), patch('urllib.request.urlopen',return_value=completion({'text':text})):
                ai_service._cache.clear()
                self.assertEqual(ai_service.generate(facts,'Объясни','Факты')['llm'],accepted)

    def test_provider_failures_are_visible_without_secrets(self):
        for code, reason in [(401,'unauthorized'),(402,'credits'),(429,'rate_limit'),(503,'unavailable')]:
            with self.subTest(code=code), patch('urllib.request.urlopen', side_effect=HTTPError('url',code,'test-key',{},None)):
                result = ai_service.generate(self.facts, 'Объясни', 'Факты')
                self.assertFalse(result['llm'])
                self.assertEqual(result['ai']['reason'],reason)
                self.assertNotIn('test-key', json.dumps(result))

    def test_timeout_and_malformed_responses(self):
        cases = [TimeoutError(), URLError('offline')]
        for error in cases:
            with self.subTest(error=type(error)), patch('urllib.request.urlopen',side_effect=error):
                self.assertFalse(ai_service.generate(self.facts,'q','Факты')['llm'])
        for value in [b'not JSON', b'{}', b'{"choices":[]}', b'{"choices":[{"message":{}}]}']:
            with self.subTest(value=value), patch('urllib.request.urlopen',return_value=io.BytesIO(value)):
                self.assertFalse(ai_service.generate(self.facts,'q','Факты')['llm'])
        with patch('urllib.request.urlopen', return_value=completion({'text':'2'},finish_reason='length')):
            self.assertFalse(ai_service.generate(self.facts,'q','Факты')['llm'])

    def test_checklist_cannot_set_durations_or_call_tools(self):
        with patch('urllib.request.urlopen',return_value=completion({'subtask_names':['Схема','Тесты'],'duration':100})):
            self.assertFalse(ai_service.generate(self.facts,'q','Факты',names=True)['llm'])
        with patch('urllib.request.urlopen',return_value=completion({'subtask_names':['Схема','Тесты']})):
            result = ai_service.generate(self.facts,'q','Факты',names=True)
            self.assertEqual(result['subtask_names'],['Схема','Тесты'])

    def test_secret_never_sent_to_other_host(self):
        self.config_mock.return_value = {'api_key':'test-key','model':'x','base_url':'https://example.com','disabled':False}
        with patch('urllib.request.urlopen') as network:
            self.assertFalse(ai_service.generate(self.facts,'q','Факты')['llm'])
            network.assert_not_called()

    def test_offline_status_does_not_claim_model_response(self):
        self.config_mock.return_value = {'api_key':'','model':ai_service.DEFAULT_MODEL,'base_url':ai_service.DEFAULT_BASE,'disabled':False}
        with patch('urllib.request.urlopen') as network:
            result = ai_service.generate(self.facts,'q','Факты')
            self.assertEqual(result['ai']['source'],'rules')
            network.assert_not_called()
        self.assertFalse(ai_service.status()['configured'])
        self.assertNotIn('api_key',ai_service.status())

class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = patch.multiple(pm, DATA_DIR=self.temp.name, DB_FILE=str(Path(self.temp.name)/'db.json'))
        self.settings.start(); self.addCleanup(self.settings.stop)
        self.no_network = patch.dict(os.environ, {'PM_RADAR_AI_DISABLED':'1'})
        self.no_network.start(); self.addCleanup(self.no_network.stop)
        seed_legacy_demo(pm)
        self.client = pm.app.test_client()
        self.base = '/api/projects/demo-migration'
        self.client.get(self.base)

    def db(self): return Path(pm.DB_FILE).read_bytes()

    def test_sandbox_moves_start_not_duration_and_does_not_save(self):
        before = self.db()
        data = self.client.post(self.base+'/sandbox',json={'task_id':'backend','shift_days':3}).get_json()
        self.assertEqual(data['fact']['duration_delta'],3)
        self.assertEqual(data['fact']['new_start'],9)
        self.assertEqual(data['fact']['task_duration'],10)
        self.assertNotIn('Разработка backend',data['fact']['affected'])
        self.assertIn('Тестирование',data['fact']['affected'])
        self.assertEqual(before,self.db())
        self.assertEqual(data['ai']['source'],'rules')
        self.client.post(self.base+'/impact',json={'task_id':'backend','changes':{'start_delay':3},'apply':True})
        saved = self.client.get(self.base).get_json()
        task = next(t for t in saved['project']['tasks'] if t['id']=='backend')
        self.assertEqual((task['duration'],task['start_delay']),(10,3))
        self.assertEqual(saved['analysis']['summary']['project_duration'],32)

    def test_parallel_reserve_absorbs_one_of_three_days(self):
        tasks = [dict(id='a',name='Разработка',duration=5,dependencies=[],status='todo'),
                 dict(id='b',name='Дизайн',duration=6,dependencies=[],status='todo'),
                 dict(id='c',name='Тестирование',duration=2,dependencies=['a','b'],status='todo')]
        before = analyze(tasks,9)
        after = analyze(simulate(tasks,{'a':{'start_delay':3}}),9)
        self.assertEqual(diff_analysis(before,after)['duration_delta'],2)
        self.assertEqual(after['summary']['project_duration'],10)
        self.assertTrue(after['summary']['deadline_breached'])
        self.assertEqual(tasks[0]['duration'],5)
        self.assertNotIn('start_delay',tasks[0])

    def test_completed_and_impossible_early_start_rejected(self):
        for task,shift in [('analysis',3),('backend',-1)]:
            with self.subTest(task=task):
                self.assertEqual(self.client.post(self.base+'/sandbox',json={'task_id':task,'shift_days':shift}).status_code,400)

    def test_fast_sandbox_does_not_wait_for_model(self):
        with patch.object(ai_service,'generate') as model:
            data = self.client.post(self.base+'/sandbox',json={'task_id':'backend','shift_days':3,'explain':False}).get_json()
            self.assertEqual(data['ai']['source'],'pending')
            model.assert_not_called()

    def test_every_ai_route_gets_structured_facts_and_is_read_only(self):
        result = {'text':'Объяснение DeepSeek','llm':True,'ai':{'source':'llm','model':ai_service.DEFAULT_MODEL}}
        routes = [('get','/radar',None),('get','/explain/backend',None),('get','/report.md',None),
            ('post','/assistant',{'message':'Какие задачи уже выполнены?'}),
            ('post','/sandbox',{'task_id':'backend','shift_days':3}),
            ('post','/simulate',{'changes':{'backend':{'duration':3}}})]
        before = self.db()
        for method,path,body in routes:
            with self.subTest(path=path), patch.object(ai_service,'generate',return_value=result) as model:
                response = getattr(self.client,method)(self.base+path,**({'json':body} if body else {}))
                self.assertEqual(response.status_code,200)
                self.assertEqual(model.call_count,1)
                facts = model.call_args.args[0]
                self.assertIn('tasks',facts)
                self.assertIn('statistics',facts)
                self.assertEqual(facts['statistics']['done_count'],2)
                self.assertIn('workload',facts)
                self.assertEqual(before,self.db())

    def test_checklist_is_only_proposed_and_python_assigns_days(self):
        before = self.db()
        result = {'text':'Предложение','llm':True,'ai':{'source':'llm','model':ai_service.DEFAULT_MODEL},
                  'subtask_names':['Схема данных','Эндпоинты','Автотесты']}
        with patch.object(ai_service,'generate',return_value=result):
            data = self.client.post(self.base+'/checklist',json={'name':'Разработка API','duration':7,'owner':'Олег Кузнецов'}).get_json()
        subs = data['suggestion']['subtasks']
        self.assertEqual([s['duration'] for s in subs],[3,2,2])
        self.assertEqual(sum(s['duration'] for s in subs),7)
        self.assertEqual(before,self.db())
        for i,s in enumerate(subs):
            s['id']=f'sub-{i}'; s['dependencies']=[f'sub-{i-1}'] if i else []
        self.assertEqual(self.client.post(self.base+'/apply-checklist',json={'subtasks':subs}).status_code,200)
        self.assertEqual(len(self.client.get(self.base).get_json()['project']['tasks']),13)

    def test_absence_scenario_is_removed_and_never_calls_model_or_changes_data(self):
        before = self.db()
        questions = ['Что будет если Олег Кузнецов уйдёт в отпуск?',
                     'Что будет если Василий Пупкин уйдёт в отпуск?',
                     'Тестирование: сотрудник в отпуске на 3 дня']
        for question in questions:
            with patch.object(ai_service,'generate') as model:
                response = self.client.post(self.base+'/assistant',json={'message':question})
                self.assertEqual(response.status_code,200)
                data = response.get_json()
                self.assertEqual(data['facts']['type'],'unsupported_scenario')
                self.assertFalse(data['llm'])
                self.assertNotIn('simulation',data['facts'])
                model.assert_not_called()
                self.assertEqual(before,self.db())

if __name__ == '__main__': unittest.main()
