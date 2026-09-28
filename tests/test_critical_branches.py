"""Every longest branch must be represented without inventing dependencies."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from schedule import analyze, simulate, diff_analysis
import assistant


def task(id, duration, deps=(), delay=0):
    return dict(id=id, name=id, duration=duration, dependencies=list(deps),
                status='todo', owner='', start_delay=delay)


class CriticalBranchesTests(unittest.TestCase):
    def test_equal_branches_and_risks_are_all_marked(self):
        tasks = [task('A',5), task('B',5), task('C',2,['A','B'])]
        result = analyze(tasks,7)
        summary = result['summary']
        self.assertEqual(summary['critical_tasks'],['A','B','C'])
        self.assertEqual(summary['critical_edges'],[['A','C'],['B','C']])
        self.assertTrue(summary['critical_branching'])
        self.assertEqual(set(summary['at_risk']),{'A','B','C'})
        self.assertEqual(summary['project_duration'],7)
        for left,right in zip(summary['critical_path'],summary['critical_path'][1:]):
            self.assertIn([left,right],summary['critical_edges'])
        text, _ = assistant.chat('Какие задачи критичны?', {'tasks':tasks}, result)
        for id in ['A','B','C']: self.assertIn(id,text)

    def test_deadline_reserve_does_not_hide_parallel_critical_branches(self):
        result = analyze([task('A',5),task('B',5),task('C',2,['A','B'])],10)
        self.assertTrue(all(t['is_critical'] for t in result['tasks']))
        self.assertEqual([t['slack'] for t in result['tasks']],[3,3,3])
        self.assertFalse(result['summary']['at_risk'])

    def test_short_branch_and_its_edge_are_not_critical(self):
        result = analyze([task('A',2),task('B',5),task('C',3,['A','B'])])
        self.assertEqual(result['summary']['critical_tasks'],['B','C'])
        self.assertEqual(result['summary']['critical_edges'],[['B','C']])
        self.assertFalse(result['summary']['critical_branching'])

    def test_waiting_period_and_separate_terminal_branches(self):
        result = analyze([task('A',5),task('B',3,delay=2)])
        self.assertEqual(result['summary']['critical_tasks'],['A','B'])
        self.assertEqual(result['summary']['critical_edges'],[])
        self.assertTrue(result['summary']['critical_branching'])

    def test_zero_duration_terminal_stays_in_representative_path(self):
        result = analyze([task('A',5),task('B',0,['A'])])
        self.assertEqual(result['summary']['critical_path'],['A','B'])
        self.assertFalse(result['summary']['critical_branching'])

    def test_scenario_recalculates_which_branches_remain_critical(self):
        tasks = [task('A',5),task('B',5),task('C',2,['A','B'])]
        before = analyze(tasks)
        after = analyze(simulate(tasks,{'A':{'start_delay':1}}))
        self.assertEqual(after['summary']['critical_tasks'],['A','C'])
        diff = diff_analysis(before,after)
        self.assertEqual(next(t for t in diff['affected_tasks'] if t['id']=='B')['criticality'],'no_longer_critical')

    def test_removed_absence_operation_is_rejected(self):
        with self.assertRaises(ValueError):
            simulate([task('A',5)],{'A':{'remove_owner':True}})
