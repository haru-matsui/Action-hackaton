import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import demo_project
from schedule import analyze, progress_summary, deadline_risk
from ai_context import project_facts
from ai_features import radar, workload_by_owner
from assistant import report


def task(id, owner='', status='todo', dependencies=(), duration=1):
    return dict(id=id,name=id,owner=owner,status=status,dependencies=list(dependencies),duration=duration)


class ProjectMetricsTests(unittest.TestCase):
    def test_demo_has_same_primary_progress_in_analysis_report_and_ai(self):
        project = demo_project()
        analysis = analyze(project['tasks'],project['deadline'])
        progress = analysis['summary']['progress']
        self.assertEqual((progress['done_count'], progress['total_tasks'], progress['completion_percent_by_task_count']), (2,10,20))
        facts = project_facts(project,analysis,'report')
        for key,value in progress.items(): self.assertEqual(facts['statistics'][key],value)
        self.assertNotIn('completion_percent_by_planned_work',facts['statistics'])
        text = report(project,analysis)
        self.assertIn('2 из 10 (20%)',text)
        self.assertNotIn('трудоёмкости',text)
        self.assertIn(facts['statistics']['status'],text)

    def test_progress_depends_on_completed_tasks_not_remaining_estimates(self):
        tasks = [task('done',status='done',duration=100),task('todo',duration=1)]
        initial = progress_summary(tasks)
        tasks[1]['duration'] = 500
        self.assertEqual(initial,progress_summary(tasks))
        self.assertEqual(initial['completion_percent_by_task_count'],50)
        tasks[1]['status'] = 'done'
        self.assertEqual(progress_summary(tasks)['completion_percent_by_task_count'],100)

    def test_progress_empty_and_rounding_boundaries(self):
        self.assertEqual(progress_summary([])['completion_percent_by_task_count'],0)
        tasks = [task(str(i),status='done' if i == 0 else 'todo') for i in range(8)]
        self.assertEqual(progress_summary(tasks)['completion_percent_by_task_count'],13)

    def test_sequential_tasks_are_distribution_signal_not_proven_overload(self):
        tasks = [task('a','Иван'),task('b','Иван',dependencies=['a']),
                 task('c','Иван',dependencies=['b']),task('d','Иван',dependencies=['c']),task('e','Мария')]
        analysis = analyze(tasks,100)
        signals = radar(analysis)
        self.assertEqual([s['type'] for s in signals],['task_distribution'])
        self.assertEqual(signals[0]['severity'],'info')
        self.assertIn('4 незавершённых задач',signals[0]['message'])
        self.assertIn('проверьте навыки и доступность',signals[0]['suggestion'])
        self.assertNotIn('перегружен',str(signals))
        self.assertNotIn('свободна',str(signals))
        self.assertEqual(workload_by_owner(analysis)['Иван']['active'],4)
        facts = project_facts({'name':'Test'},analysis,'radar')
        self.assertIn('не одновременная занятость',facts['workload_basis'])
        self.assertIn('требует внимания',report({'name':'Test'},analysis))

    def test_risk_rules_explain_reserve_without_probability(self):
        for deadline, expected in [(None,'не определён'),(9,'высокий'),(10,'средний'),
                                   (11,'умеренный'),(12,'умеренный'),(13,'низкий')]:
            with self.subTest(deadline=deadline):
                assessment = deadline_risk(10,deadline)
                self.assertEqual(assessment['level'],expected)
                self.assertIsNone(assessment['probability'])
                self.assertTrue(assessment['basis'])
                self.assertEqual(analyze([task('A',duration=10)],deadline)['summary']['risk_assessment'],assessment)

    def test_empty_and_finished_projects_do_not_claim_tight_deadline(self):
        for tasks in [[], [task('A',status='done')]]:
            self.assertFalse(radar(analyze(tasks,1)))
