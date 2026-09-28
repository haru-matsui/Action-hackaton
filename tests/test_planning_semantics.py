import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from schedule import analyze
from ai_context import project_facts
from ai_features import explain_task_simple, radar
from assistant import chat


def task(id, duration, status='todo', dependencies=()):
    return dict(id=id, name=id, duration=duration, status=status, owner='', dependencies=list(dependencies))


class PlanningSemanticsTests(unittest.TestCase):
    def test_remaining_estimate_and_deadline_use_one_planning_point(self):
        tasks = [task('Готово', 12, 'done'), task('Работа', 4, 'in_progress', ['Готово']),
                 task('Проверка', 3, dependencies=['Работа'])]
        data = analyze(tasks, 10)
        self.assertEqual([t['remaining_duration'] for t in data['tasks']], [0,4,3])
        self.assertEqual(data['tasks'][0]['duration'], 12)
        self.assertEqual(data['summary']['project_duration'], 7)
        self.assertFalse(data['summary']['status_conflicts'])
        self.assertNotIn('Готово',data['summary']['critical_tasks'])
        self.assertEqual(data['summary']['critical_path'],['Работа','Проверка'])
        facts = project_facts({'name':'Test'}, data, 'test')
        self.assertFalse(facts['time_model']['actual_dates_known'])
        self.assertFalse(facts['time_model']['forecast_conditional'])
        self.assertIn('оставшаяся оценка', explain_task_simple('Работа', data))
        self.assertIn('не добавляет оставшейся работы', explain_task_simple('Готово', data))

    def test_status_conflicts_are_explicit_without_inventing_actual_dates(self):
        for status in ['in_progress','done']:
            data = analyze([task('Предшественник', 5), task('Задача', 3, status, ['Предшественник'])])
            self.assertEqual(data['summary']['status_conflicts'][0]['unfinished_dependencies'], ['Предшественник'])
            self.assertTrue(project_facts({'name':'Test'},data,'test')['time_model']['forecast_conditional'])
            self.assertTrue(any(s['type']=='status_conflict' for s in radar(data)))
            text = explain_task_simple('Задача', data)
            self.assertIn('противоречие',text)
            self.assertNotIn('Все предшественники выполнены',text)
            self.assertNotIn('не можешь начать',text)
            reply, _ = chat('Какие риски?', {'name':'Test','tasks':data['tasks']}, data)
            self.assertIn('предшественники не завершены',reply)

    def test_dependency_does_not_claim_actual_stoppage(self):
        tasks = [task('А',3), task('Б',2,dependencies=['А'])]
        data = analyze(tasks)
        self.assertNotIn('стоят', explain_task_simple('А',data))
        self.assertIn('По плану начало зависит', explain_task_simple('Б',data))
        tasks[0]['start_delay'] = 2
        self.assertIn('ожидание 2',explain_task_simple('А',analyze(tasks)))

    def test_empty_and_completed_plans_have_no_remaining_work(self):
        for tasks in [[],[task('Готово',10,'done')]]:
            data = analyze(tasks,30)
            self.assertEqual(data['summary']['project_duration'],0)
            self.assertFalse(data['summary']['status_conflicts'])
            self.assertEqual(data['summary']['critical_tasks'],[])
            self.assertEqual(data['summary']['critical_path'],[])
