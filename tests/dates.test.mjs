import test from 'node:test';
import assert from 'node:assert/strict';
import {dateText, projectDay, taskPeriod} from '../backend/static/js/dates.js';
import {renderProject, renderSandbox, impactMarkup, timelineScale} from '../backend/static/js/views.js';

test('date presentation preserves the server date regardless of browser timezone', () => {
  const previous = process.env.TZ;
  try {
    for (const zone of ['Pacific/Honolulu','Asia/Yekaterinburg','Pacific/Kiritimati']) {
      process.env.TZ = zone;
      assert.equal(dateText('2026-09-28'),'28.09.2026');
      assert.equal(dateText('2026-12-31',true),'31 дек. 2026');
    }
  } finally { if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous; }
  assert.equal(dateText(null),'—');
  assert.equal(dateText('<img>'),'—');
  assert.equal(projectDay({configured:true,project_started:true,current_workday:6}),'6-й рабочий день');
  assert.equal(projectDay({configured:true,project_started:false}),'Проект ещё не начался');
  assert.equal(projectDay({configured:true,project_started:true,completed_workdays:5}),'Выходной · прошло 5 раб. дн.');
  assert.equal(taskPeriod({status:'done',planned_start_date:null}),'Завершена');
});

function dom(t) {
  const previous = globalThis.document, nodes = new Map();
  t.after(() => { if (previous === undefined) delete globalThis.document; else globalThis.document = previous; });
  globalThis.document = {querySelector(selector) {
    if (!nodes.has(selector)) nodes.set(selector,{innerHTML:'',textContent:'',style:{},classList:{toggle(){}},setAttribute(){}});
    return nodes.get(selector);
  }};
  return nodes;
}

function analysis() {
  return {calendar:{configured:true,start_date:'2026-09-21',today:'2026-09-28',planning_date:'2026-09-28',
    project_started:true,current_workday:6,planning_offset:5,today_offset:5,deadline_date:'2026-10-02',deadline_offset:9,
    max_day:12,step:5,ticks:[{offset:0,date:'2026-09-21'},{offset:5,date:'2026-09-28'},{offset:10,date:'2026-10-05'}]},
    summary:{project_duration:2,project_deadline:5,deadline_reserve:3,forecast_finish_date:'2026-09-29',
      deadline_date:'2026-10-02',deadline_breached:false,at_risk:[],critical_tasks:['a'],critical_path:['a'],critical_edges:[],
      progress:{done_count:1,total_tasks:2,completion_percent_by_task_count:50}},
    tasks:[{id:'done',name:'Готово',status:'done',duration:12,remaining_duration:0,dependencies:[],slack:0,early_start:0,early_finish:0},
      {id:'a',name:'Работа',status:'todo',duration:2,remaining_duration:2,dependencies:[],slack:3,is_critical:true,
        early_start:0,early_finish:2,planned_start_date:'2026-09-28',planned_finish_date:'2026-09-29',calendar_start_offset:5,calendar_finish_offset:7}]};
}

test('calendar is consistent in heading, metric, table and draggable bar; done tasks have no invented date', t => {
  const nodes = dom(t), data = analysis();
  const state = {project:{name:'Календарь',tasks:data.tasks},analysis:data,owners:[]};
  renderProject(state);
  assert.match(nodes.get('#calendarSummary').innerHTML,/6-й рабочий день/);
  assert.equal(nodes.get('#calendarAction').textContent,'Изменить даты');
  assert.match(nodes.get('#badges').innerHTML,/29 сент. 2026/);
  assert.match(nodes.get('#badges').innerHTML,/Дедлайн 02.10.2026/);
  assert.match(nodes.get('#timeline').innerHTML,/Сегодня · 28.09.2026/);
  assert.match(nodes.get('#timeline').innerHTML,/data-original-left="41.66666666666667"/);
  assert.match(nodes.get('#timeline').innerHTML,/gantt-completed/);
  assert.doesNotMatch(nodes.get('#timeline').innerHTML,/gantt-bar done/);
  assert.match(nodes.get('#taskTable').innerHTML,/28.09.2026 → 29.09.2026/);
  const scale = timelineScale({...state,baselineAnalysis:{calendar:{...data.calendar,max_day:20}}});
  assert.equal(scale.maxDay,20);
  assert.equal(scale.percent(5),25);
  renderProject({...state,analysis:{...data,calendar:{configured:false}}});
  assert.equal(nodes.get('#calendarAction').textContent,'Указать даты');
  assert.doesNotMatch(nodes.get('#calendarSummary').innerHTML,/Начало \d/);
});

test('dated deadline line aligns with its date and adjacent date ticks remain visible', t => {
  const nodes = dom(t), data = analysis();
  data.calendar = {...data.calendar,axis_start:'2026-09-22',start_date:'2026-09-22',
    deadline_date:'2026-10-22',deadline_offset:22,max_day:32,step:5,
    ticks:[{offset:0,date:'2026-09-22'},{offset:5,date:'2026-09-29'},
      {offset:10,date:'2026-10-06'},{offset:15,date:'2026-10-13'},
      {offset:20,date:'2026-10-20'},{offset:25,date:'2026-10-27'}]};
  data.summary.deadline_date = '2026-10-22';
  renderProject({project:{name:'Календарь',tasks:data.tasks},analysis:data,owners:[]});
  const html = nodes.get('#timeline').innerHTML;
  assert.match(html,/>20\.10\.2026<\/span>/);
  assert.match(html,/>27\.10\.2026<\/span>/);
  assert.match(html,/class="deadline-label" style="left:68\.75%">Дедлайн · 22\.10\.2026/);
  assert.match(html,/class="deadline-axis-mark" style="left:68\.75%"/);
  assert.match(html,/class="gantt-deadline" style="left:68\.75%"/);
  assert.ok(20 / 32 * 100 < 68.75 && 68.75 < 25 / 32 * 100);
});

test('dated sandbox keeps AI after metrics and tasks; impact shows dates rather than abstract days', t => {
  const nodes = dom(t), after = analysis();
  const diff = {old_duration:1,new_duration:2,duration_delta:1,old_finish_date:'2026-09-28',new_finish_date:'2026-09-29',
    affected_tasks:[],consequences:[],edited_tasks:[{name:'Работа',changes:{duration:{before:1,after:2}},
      schedule_changes:{early_finish:{before:1,after:2},planned_finish_date:{before:'2026-09-28',after:'2026-09-29'}}}]};
  const data = {after,diff,explanation:'Объяснение нейросети',changes:[{task_id:'a',task:'Работа',old_start_date:'2026-09-25',new_start_date:'2026-09-28'}]};
  renderSandbox({active:true,phase:'ready',aiPhase:'ready',data,canApply:true,dirty:true});
  const html = nodes.get('#sandboxInfo').innerHTML;
  assert.match(html,/25.09.2026 → 28.09.2026/);
  assert.match(html,/Дедлайн 02.10.2026/);
  assert.ok(html.indexOf('Ваши изменения') < html.indexOf('Объяснение нейросети'));
  assert.ok(html.indexOf('Следом сдвинутся') < html.indexOf('Объяснение нейросети'));
  const impact = impactMarkup(data);
  assert.match(impact,/28.09.2026/);
  assert.match(impact,/29.09.2026/);
  assert.doesNotMatch(impact,/День 1/);
});
