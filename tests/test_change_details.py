import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from schedule import analyze, diff_analysis
from assistant import explain_change


def task(id, duration, dependencies=()):
    return dict(id=id,name=id,duration=duration,owner='',status='todo',dependencies=list(dependencies))


class ChangeDetailsTests(unittest.TestCase):
    def compare(self, tasks, changes, deadline=None):
        changed = copy.deepcopy(tasks)
        for item in changed:
            item.update(changes.get(item['id'], {}))
        before, after = analyze(tasks,deadline), analyze(changed,deadline)
        return before, after, diff_analysis(before,after)

    def test_noncritical_duration_and_reserve_change_without_moving_project(self):
        before, after, diff = self.compare([task('Короткая',5),task('Длинная',10)], {'Короткая':{'duration':7}})
        self.assertEqual((diff['old_duration'],diff['new_duration']),(10,10))
        self.assertEqual([t['id'] for t in diff['edited_tasks']],['Короткая'])
        self.assertEqual(diff['consequences'],[])
        item = diff['edited_tasks'][0]
        self.assertEqual(item['changes']['duration'],{'before':5,'after':7})
        self.assertEqual(item['schedule_changes']['early_finish'],{'before':5,'after':7})
        self.assertEqual(item['schedule_changes']['slack'],{'before':5,'after':3})
        self.assertNotIn('shift_days',item)
        text = explain_change(before,after,diff,'Короткая')
        self.assertIn('5 → 7',text)
        self.assertIn('5 → 3',text)
        self.assertNotIn('Сдвинулись последующие',text)

    def test_owner_and_name_changes_do_not_imply_faster_work(self):
        before, after, diff = self.compare([task('A',5)], {'A':{'name':'Новое имя','owner':'Мария'}},10)
        self.assertEqual(set(diff['edited_tasks'][0]['changes']),{'name','owner'})
        self.assertEqual(diff['edited_tasks'][0]['schedule_changes'],{})
        text = explain_change(before,after,diff,'Новое имя')
        self.assertIn('сама по себе не сокращает',text)
        self.assertNotIn('изменение попало в резерв',text)
        self.assertFalse(diff['requires_action'])

    def test_dependencies_status_and_schedule_changes_are_separate(self):
        tasks = [task('A',5),task('B',2),task('C',3,['B'])]
        _, _, diff = self.compare(tasks,{'B':{'dependencies':['A']}})
        self.assertEqual([t['id'] for t in diff['edited_tasks']],['B'])
        self.assertEqual(diff['edited_tasks'][0]['changes']['dependencies'],{'before':[],'after':['A']})
        c = next(t for t in diff['consequences'] if t['id']=='C')
        self.assertEqual((c['shift_days'],c['finish_shift_days']),(5,5))
        self.assertEqual(c['changes'],{})
        _, _, done_diff = self.compare(tasks, {'A':{'status':'done'}})
        a = next(t for t in done_diff['edited_tasks'] if t['id']=='A')
        self.assertEqual(a['schedule_changes']['remaining_duration'],{'before':5,'after':0})
        self.assertEqual(a['changes']['status'],{'before':'todo','after':'done'})

    def test_unchanged_and_reordered_dependencies_have_no_edits(self):
        tasks = [task('A',2),task('B',2),task('C',1,['A','B'])]
        _, _, diff = self.compare(tasks,{'C':{'dependencies':['B','A'],'start_delay':0}})
        self.assertEqual(diff['edited_tasks'],[])
        self.assertEqual(diff['consequences'],[])

    def test_existing_deadline_problem_is_not_marked_resolved_by_owner_change(self):
        before,after,diff = self.compare([task('A',10)],{'A':{'owner':'Ольга'}},8)
        self.assertFalse(diff['requires_action'])
        self.assertTrue(diff['has_current_issues'])
        self.assertTrue(diff['existing_issues_remain'])
        text = explain_change(before,after,diff,'A')
        self.assertIn('Ранее выявленные проблемы сохраняются',text)
        self.assertNotIn('вмешательство из-за этого изменения не требуется',text)
