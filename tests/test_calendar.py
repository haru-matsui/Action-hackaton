"""Weekday calendar and dated API flows on temporary data; no model/network calls."""
from copy import deepcopy
from datetime import date, timedelta
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import app as pm
from test_support import seed_legacy_demo
import planning_calendar as cal
import sandbox
from ai_context import project_facts
from ai_features import radar
from assistant import report, answer_what_if


def task(id='a', duration=1, status='todo', dependencies=()):
    return dict(id=id, name=id, duration=duration, status=status, dependencies=list(dependencies), owner='')


def project(tasks=None, start='2026-09-25', deadline='2026-09-28'):
    return dict(name='Календарь', start_date=start, deadline_date=deadline,
                tasks=[task()] if tasks is None else tasks)


class CalendarMathTests(unittest.TestCase):
    def test_weekday_arithmetic_matches_day_by_day_reference(self):
        for day in (date(2024, 2, 26), date(2026, 12, 28)):
            for weekday in range(7):
                start = day + timedelta(days=weekday)
                for count in range(-18, 19):
                    expected = cal.next_workday(start)
                    direction = 1 if count >= 0 else -1
                    for _ in range(abs(count)):
                        expected += timedelta(days=direction)
                        while expected.weekday() >= 5:
                            expected += timedelta(days=direction)
                    self.assertEqual(cal.add_workdays(start,count), expected)
                for distance in range(-20,21):
                    end = start + timedelta(days=distance)
                    lo, hi = sorted([start,end])
                    expected = sum((lo+timedelta(days=i)).weekday() < 5 for i in range((hi-lo).days))
                    self.assertEqual(cal.working_days_between(start,end), expected * (-1 if distance < 0 else 1))

    def test_inclusive_finish_and_weekend_deadline(self):
        for duration, deadline, expected, late, reserve in [
            (1,'2026-09-25','2026-09-25',False,0),
            (1,'2026-09-27','2026-09-25',False,0),
            (2,'2026-09-27','2026-09-28',True,-1),
            (2,'2026-09-28','2026-09-28',False,0)]:
            with self.subTest(duration=duration,deadline=deadline):
                data = cal.analyze_project(project([task(duration=duration)],deadline=deadline), as_of='2026-09-25')
                self.assertEqual(data['summary']['forecast_finish_date'],expected)
                self.assertEqual(data['tasks'][0]['planned_start_date'],'2026-09-25')
                self.assertEqual(data['summary']['deadline_breached'],late)
                self.assertEqual(data['summary']['deadline_reserve'],reserve)

    def test_deadline_marker_uses_date_position_not_next_day(self):
        base = project([task(duration=29)],start='2026-09-22',deadline='2026-10-22')
        weekday = cal.analyze_project(base,as_of='2026-09-28')
        ticks = {item['date']:item['offset'] for item in weekday['calendar']['ticks']}
        self.assertEqual((ticks['2026-10-20'],weekday['calendar']['deadline_offset'],ticks['2026-10-27']),
                         (20,22,25))
        self.assertEqual(weekday['summary']['project_deadline'],23)

        base['deadline_date'] = '2026-10-03'  # Saturday: no separate weekend column.
        weekend = cal.analyze_project(base,as_of='2026-09-28')
        ticks = {item['date']:item['offset'] for item in weekend['calendar']['ticks']}
        self.assertLess(ticks['2026-09-29'],weekend['calendar']['deadline_offset'])
        self.assertEqual(weekend['calendar']['deadline_offset'],9)
        self.assertLess(weekend['calendar']['deadline_offset'],ticks['2026-10-06'])
        self.assertEqual(weekend['summary']['project_deadline'],9)
        self.assertEqual(weekend['summary']['delay_vs_deadline'],20)

    def test_today_progress_future_start_and_weekend(self):
        p = project(start='2026-09-21')
        friday = cal.analyze_project(p,as_of='2026-09-25')['calendar']
        self.assertEqual(friday['current_workday'],5)
        weekend = cal.analyze_project(p,as_of='2026-09-27')['calendar']
        self.assertIsNone(weekend['current_workday'])
        self.assertEqual(weekend['completed_workdays'],5)
        self.assertEqual(weekend['planning_date'],'2026-09-21')
        future = cal.analyze_project(project(start='2026-10-03',deadline=None),as_of='2026-09-25')['calendar']
        self.assertFalse(future['project_started'])
        self.assertEqual(future['planning_date'],'2026-10-05')
        self.assertIsNone(future['current_workday'])
        self.assertEqual(future['today_offset'],0)
        self.assertGreater(future['planning_offset'],0)

    def test_estimates_do_not_shrink_automatically_and_deadline_stays_fixed(self):
        p = project([task(duration=2)])
        snapshot = deepcopy(p)
        friday = cal.analyze_project(p,as_of='2026-09-25')
        monday = cal.analyze_project(p,as_of='2026-09-28')
        self.assertEqual(friday['summary']['forecast_finish_date'],'2026-09-28')
        self.assertEqual(monday['summary']['forecast_finish_date'],'2026-09-28')
        self.assertEqual(monday['summary']['deadline_date'],'2026-09-28')
        self.assertEqual(monday['summary']['project_duration'],2)
        self.assertEqual(monday['summary']['delay_vs_deadline'],0)
        self.assertEqual(p,snapshot)

    def test_completed_empty_and_milestone_dates_are_honest(self):
        for tasks in ([],[task(duration=12,status='done')]):
            data = cal.analyze_project(project(tasks),as_of='2026-10-10')
            self.assertIsNone(data['summary']['forecast_finish_date'])
            self.assertIsNone(data['summary']['deadline_reserve'])
            self.assertFalse(data['summary']['deadline_breached'])
            self.assertEqual(data['summary']['risk_assessment']['level'],'не определён')
            if tasks:
                self.assertIsNone(data['tasks'][0]['planned_start_date'])
                self.assertIsNone(data['tasks'][0]['planned_finish_date'])
        milestone = cal.analyze_project(project([task(duration=0)],deadline='2026-09-25'),as_of='2026-09-28')
        self.assertEqual(milestone['summary']['forecast_finish_date'],'2026-09-25')
        self.assertFalse(milestone['summary']['deadline_breached'])
        self.assertEqual(milestone['tasks'][0]['status'],'todo')
        chain = cal.analyze_project(project([task(),task('m',0,dependencies=['a'])]),as_of='2026-09-25')
        self.assertEqual(chain['tasks'][1]['planned_finish_date'],chain['summary']['forecast_finish_date'])

    def test_past_deadline_absent_deadline_and_large_range(self):
        data = cal.analyze_project(project([task(duration=2)],deadline='2026-09-25'),as_of='2026-09-30')
        self.assertEqual(data['summary']['deadline_reserve'],-1)
        self.assertEqual(data['summary']['forecast_finish_date'],'2026-09-28')
        self.assertEqual(data['summary']['risk_assessment']['level'],'высокий')
        self.assertIn('25.09.2026',radar(data)[0]['message'])
        no_deadline = cal.analyze_project(project(deadline=None),as_of='2026-09-25')
        self.assertEqual(no_deadline['summary']['risk_assessment']['level'],'не определён')
        long = cal.analyze_project(project([task(duration=100000)],deadline=None),as_of='2026-09-25')
        self.assertLess(len(long['calendar']['ticks']),12)
        with self.assertRaises(ValueError):
            cal.add_workdays(date(2026,9,25),10_000_000)

    def test_facts_report_and_what_if_share_dates(self):
        p = project([task('Разработка',2)])
        before = cal.analyze_project(p,as_of='2026-09-25')
        text, payload = answer_what_if('Что будет если Разработка задержится на 1 день?',p,before)
        self.assertEqual(payload['after']['summary']['forecast_finish_date'],'2026-09-29')
        self.assertIn('29.09.2026',text)
        self.assertIn('28.09.2026',report(p,before))
        facts = project_facts(p,before,'report')
        self.assertEqual(facts['calendar']['today'],'2026-09-25')
        self.assertFalse(facts['time_model']['actual_dates_known'])
        self.assertNotIn('Нет календарных дат',str(facts))


class CalendarApiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for context in [patch.multiple(pm, DATA_DIR=temp.name, DB_FILE=str(Path(temp.name)/'db.json')),
                        patch.dict(os.environ, {'PM_RADAR_AI_DISABLED':'1'})]:
            context.start(); self.addCleanup(context.stop)
        self.clock = patch.object(cal,'today',return_value=date(2026,9,25)).start()
        self.revision_clock = patch.object(sandbox,'today',return_value=date(2026,9,25)).start()
        self.addCleanup(patch.stopall)
        seed_legacy_demo(pm)
        self.client = pm.app.test_client()
        self.base = '/api/projects/demo-migration'

    def test_legacy_project_stays_undated_until_user_saves_start(self):
        initial = self.client.get(self.base).get_json()
        original = Path(pm.DB_FILE).read_bytes()
        self.assertFalse(initial['analysis']['calendar']['configured'])
        self.assertEqual(initial['analysis']['summary']['project_duration'],29)
        self.assertNotIn('start_date',initial['project'])
        self.client.get(self.base)
        self.assertEqual(original,Path(pm.DB_FILE).read_bytes())
        changed = self.client.put(self.base,json={'start_date':'2026-09-25','deadline_date':'2026-11-05',
                                                  'base_revision':initial['revision']})
        self.assertEqual(changed.status_code,200)
        data = changed.get_json()
        self.assertEqual(data['project']['tasks'],initial['project']['tasks'])
        self.assertEqual(data['analysis']['calendar']['current_workday'],1)
        self.assertIsNone(data['project']['deadline'])
        self.assertEqual(self.client.get(self.base).get_json()['analysis'],data['analysis'])

    def test_invalid_dates_do_not_write_and_dated_project_uses_dates_only(self):
        self.client.get(self.base)
        original = Path(pm.DB_FILE).read_bytes()
        for body in [{'start_date':None},{'start_date':True},{'start_date':'2026-02-30'},
                     {'start_date':'2026-9-1'}, {'start_date':'1999-12-31'},
                     {'start_date':'2026-09-25','deadline_date':'2026-09-24'},
                     {'deadline_date':'2026-10-10'}, {'start_date':'2026-09-25','deadline':30}]:
            with self.subTest(body=body):
                self.assertEqual(self.client.put(self.base,json=body).status_code,400)
                self.assertEqual(original,Path(pm.DB_FILE).read_bytes())
        self.client.put(self.base,json={'start_date':'2026-09-25'})
        self.assertEqual(self.client.put(self.base,json={'deadline':30}).status_code,400)
        result = self.client.put(self.base,json={'deadline_date':None}).get_json()
        self.assertIsNone(result['analysis']['summary']['deadline_date'])

    def new_project(self):
        body = project([task('Разработка',1),task('Тест',1,dependencies=['Разработка'])])
        response = self.client.post('/api/projects',json=body)
        self.assertEqual(response.status_code,201)
        return response.get_json()

    def test_repeated_start_changes_recalculate_tasks_and_forecast_with_fixed_deadline(self):
        original = self.new_project()
        base = '/api/projects/' + original['project']['id']
        revision = original['revision']
        for start, finish in [('2026-09-28','2026-09-29'),('2026-09-25','2026-09-28')]:
            response = self.client.put(base,json={'start_date':start,'base_revision':revision})
            self.assertEqual(response.status_code,200,response.get_json())
            data = response.get_json()
            self.assertEqual(data['analysis']['tasks'][0]['planned_start_date'],start)
            self.assertEqual(data['analysis']['summary']['forecast_finish_date'],finish)
            self.assertEqual(data['analysis']['summary']['deadline_date'],'2026-09-28')
            self.assertEqual(self.client.get(base).get_json()['analysis'],data['analysis'])
            revision = data['revision']

    def test_past_starts_are_rejected_except_preserving_existing_date_and_demo_defaults(self):
        response = self.client.post('/api/projects',json=project(start='2026-09-24'))
        self.assertEqual(response.status_code,400)
        demo = self.client.post(self.base+'/reset-demo',json={}).get_json()
        self.assertEqual(demo['project']['start_date'],'2026-09-22')
        self.assertEqual(demo['project']['deadline_date'],'2026-11-03')
        self.assertEqual(demo['analysis']['calendar']['planning_date'],'2026-09-22')
        self.assertEqual(demo['analysis']['summary']['forecast_finish_date'],'2026-10-30')
        self.assertEqual(demo['analysis']['summary']['project_deadline'],31)
        self.assertEqual(demo['analysis']['summary']['deadline_reserve'],2)
        self.assertEqual(demo['analysis']['calendar']['deadline_offset'],30)
        data = self.client.put(self.base,json={'start_date':'2026-09-22','deadline_date':'2026-10-23'})
        self.assertEqual(data.status_code,200)
        unchanged = Path(pm.DB_FILE).read_bytes()
        for start in ['2026-09-21','2026-09-24']:
            self.assertEqual(self.client.put(self.base,json={'start_date':start}).status_code,400)
            self.assertEqual(Path(pm.DB_FILE).read_bytes(),unchanged)
        self.assertEqual(self.client.put(self.base,json={'start_date':'2026-09-25'}).status_code,200)
        seed = __import__('json').loads(Path(pm.DEFAULT_DB_FILE).read_text(encoding='utf-8'))['projects']['demo-migration']
        self.assertEqual((seed['start_date'],seed['deadline_date']),('2026-09-22','2026-11-03'))

    def test_dated_sandbox_preview_apply_and_explanation_use_same_dates(self):
        original = self.new_project()
        base = '/api/projects/' + original['project']['id']
        db = Path(pm.DB_FILE).read_bytes()
        body = {'shifts':{'Разработка':1},'base_revision':original['revision'],'explain':False}
        preview = self.client.post(base+'/sandbox',json=body).get_json()
        self.assertEqual(preview['changes'][0]['new_start_date'],'2026-09-28')
        self.assertEqual(preview['diff']['new_finish_date'],'2026-09-29')
        self.assertEqual(preview['after']['summary']['deadline_date'],'2026-09-28')
        self.assertEqual(db,Path(pm.DB_FILE).read_bytes())
        explanation = self.client.post(base+'/sandbox',json={**body,'explain':True}).get_json()
        self.assertEqual(explanation['after'],preview['after'])
        self.assertIn('29.09.2026',explanation['explanation'])
        saved = self.client.post(base+'/sandbox/apply',json={
            'shifts':preview['shifts'],'base_revision':preview['base_revision'],
            'scenario_key':preview['scenario_key']}).get_json()
        self.assertEqual(saved['analysis'],preview['after'])
        self.assertEqual(saved['project']['tasks'][0]['duration'],1)

    def test_midnight_invalidates_scenario_and_impact_receipt_without_writing(self):
        initial = self.new_project()
        base = '/api/projects/' + initial['project']['id']
        request = {'shifts':{'Разработка':1},'base_revision':initial['revision'],'explain':False}
        scenario = self.client.post(base+'/sandbox',json=request).get_json()
        impact = self.client.post(base+'/impact',json={'task_id':'Разработка','changes':{'duration':2},
            'apply':False,'base_revision':initial['revision']}).get_json()
        db = Path(pm.DB_FILE).read_bytes()
        self.clock.return_value = self.revision_clock.return_value = date(2026,9,28)
        current = self.client.get(base).get_json()
        self.assertNotEqual(current['revision'],initial['revision'])
        self.assertEqual(current['analysis']['summary']['forecast_finish_date'],'2026-09-28')
        for response in [self.client.post(base+'/sandbox',json=request),
                         self.client.post(base+'/sandbox/apply',json={'shifts':request['shifts'],
                             'base_revision':initial['revision'],'scenario_key':scenario['scenario_key']}),
                         self.client.post(base+'/impact/explanation',json={'explanation_id':impact['explanation_id']})]:
            self.assertEqual(response.status_code,409)
        self.assertEqual(db,Path(pm.DB_FILE).read_bytes())
        self.assertEqual(self.client.get('/api/calendar').get_json()['today'],'2026-09-28')


if __name__ == '__main__':
    unittest.main()
