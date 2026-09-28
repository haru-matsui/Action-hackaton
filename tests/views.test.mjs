import test from 'node:test';
import assert from 'node:assert/strict';
import {renderProject, impactMarkup} from '../backend/static/js/views.js';

test('all parallel critical branches appear in the chart, graph, metrics and consequences', t => {
  const nodes = new Map();
  const original = globalThis.document;
  t.after(() => { if (original === undefined) delete globalThis.document; else globalThis.document = original; });
  globalThis.document = {querySelector:selector => {
    if (!nodes.has(selector)) nodes.set(selector, {innerHTML:'',textContent:'',style:{},classList:{toggle(){}},setAttribute(){}});
    return nodes.get(selector);
  }};
  const tasks = ['A','B','C'].map((id, index) => ({id,name:id,owner:'',status:'todo',
    duration:index===2 ? 2 : 5, early_start:index===2 ? 5 : 0, early_finish:index===2 ? 7 : 5,
    slack:0,is_critical:true,at_risk:true,dependencies:index===2 ? ['A','B'] : []}));
  const summary = {project_duration:7, project_deadline:7, deadline_breached:false,
    critical_path:['A','C'],critical_tasks:['A','B','C'],critical_edges:[['A','C'],['B','C']],
    critical_branching:true,at_risk:['A','B','C']};
  const analysis = {tasks,summary};
  renderProject({project:{name:'Проверка',tasks},analysis,owners:[]});
  assert.equal((nodes.get('#graph').innerHTML.match(/class="graph-edge critical"/g) || []).length,2);
  assert.equal((nodes.get('#timeline').innerHTML.match(/gantt-bar todo critical/g) || []).length,3);
  assert.equal(nodes.get('#criticalTitle').textContent,'Критические ветки');
  assert.equal((nodes.get('#criticalPath').innerHTML.match(/class="path-node/g) || []).length,3);
  assert.ok(!nodes.get('#criticalPath').innerHTML.includes('path-arrow'));
  analysis.summary.progress = {done_count:2,in_progress_count:1,total_tasks:10,completion_percent_by_task_count:20};
  const progressTasks = Array.from({length:10}, (_, i) => ({...tasks[0],id:`t${i}`,name:`t${i}`,dependencies:[],status:i<2?'done':'todo',remaining_duration:i<2?0:5}));
  renderProject({project:{name:'Прогресс',tasks:progressTasks},analysis:{tasks:progressTasks,summary:{...summary,critical_tasks:[],critical_path:[],critical_edges:[]}},owners:[]});
  assert.equal(nodes.get('#sidePercent').textContent,'20%');
  assert.equal(nodes.get('#sideProgressText').textContent,'2 из 10 задач выполнено');
  assert.match(nodes.get('#badges').innerHTML,/20% задач завершено/);
  assert.match(nodes.get('#taskTable').innerHTML,/<td>0 дн\.<\/td>/);
  const html = impactMarkup({after:analysis,diff:{affected_tasks:[],old_duration:7,new_duration:7,duration_delta:0}});
  assert.match(html,/Критические задачи всех веток/);
  assert.match(html,/A, B, C/);
});

test('impact distinguishes edited estimates, consequences and existing risks', () => {
  const after = {tasks:[{id:'a',name:'Короткая'}],summary:{project_deadline:10,deadline_breached:false,
    at_risk:[],critical_path:[],critical_tasks:[],critical_branching:false}};
  const diff = {old_duration:10,new_duration:10,duration_delta:0,requires_action:false,
    affected_tasks:[],consequences:[],edited_tasks:[{id:'a',name:'Короткая',type:'updated',
      changes:{duration:{before:5,after:7}},schedule_changes:{slack:{before:5,after:3},early_finish:{before:5,after:7}}}]};
  const html = impactMarkup({after,diff});
  assert.match(html,/Ваши изменения/);
  assert.match(html,/Короткая/);
  assert.match(html,/5 дн\./);
  assert.match(html,/7 дн\./);
  assert.match(html,/3 дн\./);
  assert.match(html,/Последующие задачи не сдвигаются/);
  diff.existing_issues_remain = true;
  assert.match(impactMarkup({after,diff}),/Прежние риски сохраняются/);
  diff.edited_tasks[0].changes.owner = {before:'',after:'<script>alert(1)</script>'};
  assert.ok(!impactMarkup({after,diff}).includes('<script>'));
});
