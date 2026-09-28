import {$, $$, escapeHTML as esc, icon, hydrateIcons, richText, toast, busy, confirmAction, aiNotice} from './ui.js';
import {request, projectPath} from './api.js';
import {renderProject, timelineScale, impactMarkup, renderSandbox, renderRadar} from './views.js';
import {SandboxSession} from './sandbox.js';
import {WorkspaceNavigation} from './workspace.js';
import {ImpactExplanation} from './impact.js';
import {forecastValue} from './dates.js';
import {dateRange, bindDateField, setDateField} from './date-input.js';

const state = {pid:null, project:null, analysis:null, owners:[], view:'timeline', sandbox:false, loading:false};
const histories = new Map(), pendingChats = new Set(), radarSignatures = new Map();
let loadVersion = 0, editing = null, checklist = [], taskBusy = false;
const dateRules = {p:{},d:{}};
let explanationTarget = null, dateEditing = null, datesSaving = false, creatingProject = false;
const impactExplanation = new ImpactExplanation((pid, body, signal) =>
  request(projectPath(pid, '/impact/explanation'), {method:'POST', body, signal}));
function cancelImpactExplanation() { impactExplanation.cancel(); explanationTarget = null; }
function explainImpact(pid, data, target, form = null) {
  explanationTarget = target;
  const current = () => state.pid === pid && state.revision === data.result_revision
    && (target === 'preview' ? $('#taskModal').open && editing === form : !$('#impactCard').hidden);
  const render = result => {
    if (target === 'preview') $('#taskPreview').innerHTML = impactMarkup(result);
    else showImpact(result);
  };
  void impactExplanation.run(pid, data, current, result => {
    render(result);
    if (target === 'saved') addMessage(result.explanation, 'ai', pid, false, result.ai);
  }, error => {
    if (error.code === 'revision_conflict') {
      if (target === 'preview') $('#taskPreview').innerHTML = previewPlaceholder;
      else $('#impactCard').hidden = true;
      toast(error.message, true);
    } else render({...data, ai:{source:'rules', reason:'unavailable'}});
  });
}
const sandboxSession = new SandboxSession((pid, suffix, body, signal) =>
  request(projectPath(pid, suffix), {method:'POST', body, signal}), () => displayProject());
const previewPlaceholder = `<div class="preview-empty">${icon('branches')}<h3>Сначала оцените последствия</h3><p>Узнайте, как изменение повлияет на сроки и связанные задачи, перед сохранением.</p></div>`;
const history = pid => { if (!histories.has(pid)) histories.set(pid, []); return histories.get(pid); };

function renderMessages() {
  const messages = state.pid ? history(state.pid) : [];
  $('#messages').innerHTML = messages.map(item => `<article class="message ${item.role}${item.auto ? ' auto' : ''}">${item.role === 'ai' ? `<div class="message-label">${icon(item.auto ? 'radar' : 'sparkles')}${item.auto ? 'Радар проекта' : 'PM Radar'}</div>` : ''}<div class="message-body">${aiNotice(item)}${richText(item.text)}</div></article>`).join('') + (pendingChats.has(state.pid) ? '<div class="typing-dots" role="status" aria-label="Ассистент готовит ответ"><i></i><i></i><i></i></div>' : '');
  const latest = $('#messages').lastElementChild;
  if (latest) $('#messages').scrollTop += latest.getBoundingClientRect().top - $('#messages').getBoundingClientRect().top - 18;
  $('#btnSend').disabled = !state.pid || pendingChats.has(state.pid);
}
function addMessage(text, role = 'ai', pid = state.pid, auto = false, ai = null) {
  history(pid).push({text, role, auto, ai});
  if (pid === state.pid) renderMessages();
}
function quickPrompts() {
  const task = state.analysis?.tasks.find(item => item.is_critical && item.status !== 'done');
  const prompts = [
    ['Риски проекта', 'Какие риски есть в проекте?'],
    ['Что если задержка?', task ? `Что будет, если ${task.name} задержится на 3 дня?` : 'Покажи критический путь'],
    ['Критический путь', 'Покажи критический путь'],
    ['Что делать?', 'Что нужно сделать, чтобы снизить риски проекта?'],
  ];
  $('#qchips').innerHTML = state.pid ? prompts.map(([label, question]) => `<button data-question="${esc(question)}">${esc(label)}${icon('arrowUpRight')}</button>`).join('') : '';
}
async function refreshProjects(preferred = state.pid) {
  const projects = await request('/api/projects');
  $('#projectSel').innerHTML = projects.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('') || '<option value="">Нет проектов</option>';
  const pid = projects.find(p => p.id === preferred)?.id || projects[0]?.id;
  if (pid) { $('#projectSel').value = pid; await openProject(pid); }
  else {
    ++loadVersion;
    Object.assign(state, {pid:null, project:null, analysis:null, owners:[]});
    clearSandbox(); displayProject(); quickPrompts(); renderMessages();
    $('#radarSummary').innerHTML = `<span class="radar-orbit">${icon('folder')}</span><div><strong>Создайте первый проект</strong><p>Ассистент подключится к вашему плану</p></div>`;
    $('#impactCard').hidden = true;
    $('#saveState').innerHTML = '<i></i>Всё сохранено';
  }
}
async function openProject(pid) {
  if (sandboxSession.phase === 'applying') return;
  cancelImpactExplanation(); $('#impactCard').hidden = true;
  const version = ++loadVersion;
  clearSandbox(); state.loading = true; displayProject();
  $('#saveState').textContent = 'Загрузка…';
  let payload;
  try { payload = await request(projectPath(pid)); }
  catch (error) {
    if (version === loadVersion) {
      state.loading = false; displayProject();
      $('#projectSel').value = state.pid || '';
      $('#saveState').textContent = 'Не удалось обновить';
    }
    throw error;
  }
  if (version !== loadVersion) return;
  state.loading = false;
  const changed = state.pid !== pid;
  Object.assign(state, payload, {pid});
  clearSandbox();
  if (changed) { $('#impactCard').hidden = true; $('#chatInput').value = ''; }
  displayProject(); revealToday(); quickPrompts();
  if (!history(pid).length) addMessage('Я помогу разобраться в плане: объясню риски, проверю последствия изменений и подготовлю отчёт. С чего начнём?', 'ai', pid);
  renderMessages();
  $('#saveState').innerHTML = '<i></i>Всё сохранено';
  void loadRadar(pid, version);
}
async function loadRadar(pid, version) {
  try {
    const radar = await request(projectPath(pid, '/radar'));
    if (version !== loadVersion) return;
    renderRadar(radar, state);
    const signature = JSON.stringify(radar.signals);
    if (radarSignatures.get(pid) !== signature) {
      addMessage(radar.text, 'ai', pid, true, radar.ai);
    }
    radarSignatures.set(pid, signature);
  } catch (error) { toast(`Радар: ${error.message}`, true); }
}
const navigation = new WorkspaceNavigation(document, {
  beforeChange: async view => view === 'timeline' || !sandboxSession.active || await exitSandbox(),
  changed: view => {
    state.view = view;
    $('#breadcrumbView').textContent = {timeline:'Обзор проекта',table:'Все задачи',graph:'Зависимости'}[view];
    closeNav();
    if (view === 'timeline') revealToday();
  },
});
const selectView = view => navigation.select(view);
function closeNav() { $('#sidebar').classList.remove('open'); $('#navBackdrop').hidden = true; $('#menuToggle').setAttribute('aria-expanded','false'); }
const setAssistantOpen = open => navigation.assistant(open);
function focusAssistant() { closeNav(); setAssistantOpen(true); $('#assistantPanel').scrollIntoView({behavior:'smooth',block:'nearest'}); if (!sandboxSession.active) $('#chatInput').focus({preventScroll:true}); }
async function sendChat(text) {
  const pid = state.pid;
  if (!pid || sandboxSession.active || !text.trim() || pendingChats.has(pid)) return;
  pendingChats.add(pid); addMessage(text.trim(), 'user', pid);
  $('#chatInput').value = '';
  try {
    const data = await request(projectPath(pid, '/assistant'), {method:'POST',body:{message:text.trim()}});
    addMessage(data.reply, 'ai', pid, false, data.ai);
  } catch (error) { addMessage(`Не удалось получить ответ: ${error.message}. Попробуйте отправить вопрос ещё раз.`, 'ai', pid); }
  finally { pendingChats.delete(pid); if (state.pid === pid) renderMessages(); }
}

function openTask(id) {
  if (!state.project || taskBusy || state.loading) return;
  if (sandboxSession.active) { toast('Выйдите из песочницы, чтобы редактировать задачу.'); return; }
  cancelImpactExplanation(); $('#impactCard').hidden = true;
  const task = state.project.tasks.find(t => t.id === id);
  editing = {pid:state.pid, id:task?.id || `task-${crypto.randomUUID()}`, existing:Boolean(task), revision:state.revision};
  checklist = [];
  $('#taskForm').reset();
  $('#tmTitle').textContent = task ? 'Редактировать задачу' : 'Новая задача';
  $('#fName').value = task?.name || '';
  $('#fDur').value = task?.duration ?? 5;
  $('#fOwner').value = task?.owner || '';
  $('#fStatus').value = task?.status || 'todo';
  updateDurationLabel();
  $('#fDeps').innerHTML = state.project.tasks.filter(t => t.id !== task?.id).map(t => `<label class="dependency-choice"><input type="checkbox" value="${esc(t.id)}" ${task?.dependencies.includes(t.id) ? 'checked' : ''}><span>${esc(t.name)}</span></label>`).join('') || '<p class="field-hint">Других задач пока нет</p>';
  $('#tmDelete').hidden = !task; $('#tmExplain').hidden = !task;
  $('#clBox').innerHTML = ''; $('#clNote').textContent = '';
  $('#taskPreview').innerHTML = previewPlaceholder;
  $('#taskModal').showModal(); $('#fName').focus();
}
function updateDurationLabel() {
  $('#fDurLabel').textContent = {todo:'Оценка, рабочих дней', in_progress:'Осталось, рабочих дней', done:'Сохранённая оценка, рабочих дней'}[$('#fStatus').value];
}
function formTask() {
  return {id:editing.id, name:$('#fName').value.trim(), duration:Number($('#fDur').value), owner:$('#fOwner').value.trim(), status:$('#fStatus').value, dependencies:$$('#fDeps input:checked').map(input => input.value)};
}
async function taskOperation(action) {
  if (taskBusy) return;
  taskBusy = true;
  const controls = $$('#taskForm input, #taskForm select, #taskForm button');
  const previous = controls.map(control => control.disabled);
  controls.forEach(control => { control.disabled = true; });
  $('#taskForm').setAttribute('aria-busy','true');
  try { await action(); } catch (error) { toast(error.message, true); }
  finally { controls.forEach((control, i) => { control.disabled = previous[i]; }); taskBusy = false; $('#taskForm').removeAttribute('aria-busy'); }
}
function impact(applied) {
  if (taskBusy) return;
  if (!$('#taskForm').reportValidity()) return;
  cancelImpactExplanation();
  const task = formTask(), current = {...editing};
  if (!task.name) { toast('Введите название задачи', true); return; }
  const original = state.project.tasks.find(item => item.id === task.id);
  const unchanged = original && task.name === original.name && task.duration === original.duration
    && task.owner === original.owner && task.status === original.status
    && [...task.dependencies].sort().join('\0') === [...original.dependencies].sort().join('\0');
  if (!applied && unchanged) {
    $('#taskPreview').innerHTML = `<div class="preview-empty">${icon('branches')}<h3>Изменений пока нет</h3><p>Длительность задачи — ${original.duration} дн., прогноз завершения — ${forecastValue(state.analysis)}${state.analysis.calendar?.configured ? '' : ' раб. дн.'} Измените параметры задачи и снова нажмите «Оценить последствия».</p></div>`;
    return;
  }
  return taskOperation(async () => {
    const body = {task_id:task.id,changes:task,apply:applied,base_revision:current.revision};
    if (!current.existing) body.tasks = [...state.project.tasks, task];
    const data = await request(projectPath(current.pid, '/impact'), {method:'POST',body});
    if (!applied) {
      $('#taskPreview').innerHTML = impactMarkup(data);
      explainImpact(current.pid, data, 'preview', editing); return;
    }
    $('#taskModal').close();
    await refreshProjects(current.pid);
    if (state.pid === current.pid && state.revision === data.result_revision) {
      showImpact(data); explainImpact(current.pid, data, 'saved');
    }
    toast('Задача сохранена. План пересчитан.');
  });
}
function showImpact(data) { $('#impact').innerHTML = impactMarkup(data); $('#impactCard').hidden = false; }
async function deleteTask() {
  const current = {...editing};
  if (!await confirmAction('Удалить задачу?', 'Задача будет удалена из плана и зависимостей других задач.')) return;
  await taskOperation(async () => {
    const tasks = state.project.tasks.filter(t => t.id !== current.id).map(t => ({...t, dependencies:t.dependencies.filter(id => id !== current.id)}));
    await request(projectPath(current.pid), {method:'PUT',body:{tasks,base_revision:current.revision}});
    $('#taskModal').close(); $('#impactCard').hidden = true;
    await refreshProjects(current.pid); toast('Задача удалена. План пересчитан.');
  });
}
async function explainTask(id) {
  if (sandboxSession.active) { focusAssistant(); return; }
  const pid = state.pid;
  $('#exTitle').textContent = state.project.tasks.find(t => t.id === id)?.name || 'Объяснение задачи';
  $('#exText').textContent = 'Разбираю связи и последствия…';
  if (!$('#explainModal').open) $('#explainModal').showModal();
  await busy(null, async () => {
    const data = await request(projectPath(pid, `/explain/${encodeURIComponent(id)}`));
    $('#exText').innerHTML = aiNotice(data) + richText(data.explanation);
  });
}
function renderChecklist() {
  $('#clBox').innerHTML = checklist.map((task, index) => `<div class="checklist-row"><span>${index + 1}. ${esc(task.name)}</span><input data-subtask="${index}" value="${task.duration}" type="number" min="0" step="1" required aria-label="Длительность подзадачи ${esc(task.name)}"><span class="field-hint">дн.</span><button type="button" class="icon-button" data-remove-subtask="${index}" aria-label="Убрать подзадачу">${icon('x')}</button></div>`).join('') + (checklist.length ? `<div class="checklist-footer"><button type="button" class="button soft" data-action="apply-checklist">${icon('check')}Применить ${checklist.length} подзадачи</button><p class="checklist-note">${editing.existing ? 'Текущая задача будет заменена цепочкой подзадач.' : 'Подзадачи будут добавлены в проект последовательной цепочкой.'}</p></div>` : '');
}
async function generateChecklist() {
  if (!$('#taskForm').reportValidity()) return;
  const task = formTask(), current = editing;
  await busy($('#tmChecklist'), async () => {
    const data = await request(projectPath(current.pid, '/checklist'), {method:'POST',body:task});
    if (editing !== current || !$('#taskModal').open || JSON.stringify(formTask()) !== JSON.stringify(task)) return;
    checklist = data.suggestion.subtasks;
    $('#clNote').innerHTML = aiNotice(data) + esc(data.suggestion.note || 'Проверьте подзадачи и их длительность.');
    renderChecklist();
  });
}
async function applyChecklist() {
  if (!checklist.length || !$('#taskForm').reportValidity()) return;
  const current = {...editing}, task = formTask();
  await taskOperation(async () => {
    const subs = checklist.map((sub, i) => ({...sub,id:`task-${crypto.randomUUID()}`,owner:task.owner,status:task.status,start_delay:i === 0 ? state.project.tasks.find(t => t.id === current.id)?.start_delay || 0 : 0}));
    subs.forEach((sub, i) => { sub.dependencies = i ? [subs[i-1].id] : task.dependencies; });
    if (current.existing) {
      const tasks = state.project.tasks.flatMap(t => t.id === current.id ? subs : [{...t,dependencies:t.dependencies.map(id => id === current.id ? subs.at(-1).id : id)}]);
      await request(projectPath(current.pid), {method:'PUT',body:{tasks,base_revision:current.revision}});
    } else await request(projectPath(current.pid, '/apply-checklist'), {method:'POST',body:{subtasks:subs,base_revision:current.revision}});
    $('#taskModal').close(); $('#impactCard').hidden = true;
    await refreshProjects(current.pid); toast('Подзадачи добавлены. Зависимости обновлены.');
  });
}

function previewState() {
  return {...state, sandbox:sandboxSession.active, baselineAnalysis:state.analysis,
    analysis:sandboxSession.active && sandboxSession.data ? sandboxSession.data.after : state.analysis};
}
function revealToday() {
  const line = $('#timeline .gantt-today');
  const scroller = $('#timelineScroll');
  if (!line || !scroller.clientWidth) return;
  const metaWidth = $('#timeline .gantt-meta')?.offsetWidth || 0;
  const visibleWidth = scroller.clientWidth - metaWidth;
  if (line.offsetLeft < scroller.scrollLeft || line.offsetLeft > scroller.scrollLeft + visibleWidth - 60) {
    scroller.scrollLeft = Math.max(0, line.offsetLeft - 60);
  }
}
function displayProject() {
  const focusId = document.activeElement?.classList.contains('gantt-bar') ? document.activeElement.dataset.taskId : null;
  state.sandbox = sandboxSession.active;
  renderProject(previewState());
  renderSandbox(sandboxSession);
  const active = sandboxSession.active, applying = sandboxSession.phase === 'applying';
  ['btnNew','btnAddTask','btnReset','btnDelProject','btnReport','btnProjectDates'].forEach(id => {
    $(`#${id}`).disabled = active || state.loading || (id !== 'btnNew' && !state.project);
  });
  $('#projectSel').disabled = applying || state.loading;
  $('#btnSandbox').disabled = applying || state.loading || !state.analysis?.tasks.length;
  $('#planScope').textContent = active ? (sandboxSession.dirty ? 'СЦЕНАРИЙ · НЕ СОХРАНЁН' : 'ПЕСОЧНИЦА') : 'СОХРАНЁННЫЙ ПЛАН';
  $('#btnSandbox').setAttribute('aria-pressed', String(active));
  $('#baselineLegend').hidden = !active || !sandboxSession.data;
  $('#graphHint').textContent = active ? 'Связи в текущем сценарии' : 'Нажмите на узел для редактирования';
  $('#badges').setAttribute('aria-busy', String(['calculating','dragging'].includes(sandboxSession.phase)));
  $('#saveState').innerHTML = state.loading ? 'Загрузка…' : active ? (sandboxSession.dirty ? 'Сценарий не сохранён' : 'Песочница') : '<i></i>Всё сохранено';
  $('#tlHint').textContent = active ? 'Сдвигайте задачи мышью или стрелками ← →. Изменения сохранятся после применения сценария.' : 'Нажмите на задачу, чтобы увидеть детали и изменить план.';
  if (focusId) $$('#timeline .gantt-bar').find(bar => bar.dataset.taskId === focusId)?.focus({preventScroll:true});
}
let drag = null;
function releaseDrag() {
  const current = drag; drag = null;
  if (current) {
    current.bar.classList.remove('dragging');
    if ($('#timeline').hasPointerCapture(current.pointerId)) $('#timeline').releasePointerCapture(current.pointerId);
  }
  return current;
}
function clearSandbox() { releaseDrag(); sandboxSession.leave(); }
async function exitSandbox() {
  if (sandboxSession.phase === 'applying') return false;
  if (sandboxSession.dirty && !await confirmAction('Отменить сценарий?', 'Пробные изменения будут сброшены. Сохранённый план останется прежним.', 'Отменить сценарий')) return false;
  clearSandbox();
  return true;
}
$('#timeline').addEventListener('pointerdown', event => {
  const bar = event.target.closest('.gantt-bar');
  if (!sandboxSession.active || !bar || event.button !== 0 || drag) return;
  if (bar.dataset.status !== 'todo') {
    toast(bar.dataset.status === 'done' ? 'Завершённую задачу нельзя сдвинуть.' : 'Задача уже в работе. Её срок можно изменить в карточке после выхода из песочницы.');
    return;
  }
  if (!sandboxSession.pause()) return;
  event.preventDefault(); bar.focus({preventScroll:true});
  const task = state.project.tasks.find(task => task.id === bar.dataset.taskId);
  const width = bar.parentElement.getBoundingClientRect().width;
  drag = {bar, pointerId:event.pointerId, id:task.id, start:event.clientX, delta:0,
    current:sandboxSession.shifts[task.id] || 0, minimum:-(task.start_delay || 0),
    pixels:width / timelineScale(previewState()).maxDay, original:Number(bar.dataset.originalLeft), trackWidth:width};
  bar.classList.add('dragging'); $('#timeline').setPointerCapture(event.pointerId);
  renderSandbox(sandboxSession); $('#badges').setAttribute('aria-busy','true');
});
$('#timeline').addEventListener('pointermove', event => {
  if (!drag || drag.pointerId !== event.pointerId) return;
  const total = Math.min(100000 + drag.minimum, Math.max(drag.minimum, drag.current + Math.round((event.clientX - drag.start) / drag.pixels)));
  drag.delta = total - drag.current;
  drag.bar.style.left = `${drag.original + drag.delta * drag.pixels / drag.trackWidth * 100}%`;
  $('#tlHint').textContent = `${drag.delta > 0 ? '+' : ''}${drag.delta} раб. дн. · отпустите задачу для расчёта`;
});
$('#timeline').addEventListener('pointerup', event => {
  if (!drag || drag.pointerId !== event.pointerId) return;
  const current = releaseDrag();
  void sandboxSession.shift(current.id, current.delta, current.minimum);
});
function cancelDrag() {
  if (!drag) return;
  releaseDrag(); void sandboxSession.resume();
}
$('#timeline').addEventListener('pointercancel', cancelDrag);
$('#timeline').addEventListener('lostpointercapture', cancelDrag);
$('#timeline').addEventListener('keydown', event => {
  if (event.key === 'Escape' && drag) { event.preventDefault(); cancelDrag(); return; }
  const bar = event.target.closest('.gantt-bar');
  if (!sandboxSession.active || !bar || bar.dataset.status !== 'todo' || !['ArrowLeft','ArrowRight'].includes(event.key)) return;
  event.preventDefault();
  const task = state.project.tasks.find(task => task.id === bar.dataset.taskId);
  void sandboxSession.shift(task.id, event.key === 'ArrowRight' ? 1 : -1, -(task.start_delay || 0));
});
$('#btnSandbox').onclick = () => {
  if (sandboxSession.active) { void exitSandbox(); return; }
  if (!state.project || state.loading) return;
  cancelImpactExplanation();
  $('#impactCard').hidden = true;
  setAssistantOpen(true);
  sandboxSession.enter(state.pid, state.revision);
};
$('#sbExit').onclick = exitSandbox;
$('#sbReset').onclick = () => { releaseDrag(); sandboxSession.reset(); };
$('#sbRetry').onclick = () => {
  if (sandboxSession.phase === 'error') void sandboxSession.calculate();
  else void sandboxSession.retryExplanation();
};
$('#sbReload').onclick = () => busy(null, () => openProject(state.pid));
$('#sbApply').onclick = async () => {
  const data = await sandboxSession.apply();
  if (!data) return;
  Object.assign(state, data);
  sandboxSession.leave();
  quickPrompts(); radarSignatures.delete(state.pid);
  void loadRadar(state.pid, loadVersion);
  toast('Сценарий применён. План сохранён.');
};
window.addEventListener('beforeunload', event => {
  if (sandboxSession.dirty) { event.preventDefault(); event.returnValue = ''; }
});

document.addEventListener('click', event => {
  const view = event.target.closest('[data-view]');
  if (view) { event.preventDefault(); selectView(view.dataset.view); return; }
  const close = event.target.closest('[data-close]');
  if (close) { if (!datesSaving && !creatingProject) document.getElementById(close.dataset.close).close(); return; }
  const explain = event.target.closest('[data-explain]');
  if (explain) { explainTask(explain.dataset.explain); return; }
  const task = event.target.closest('[data-task-id]');
  if (task) { if (!(state.sandbox && task.classList.contains('gantt-bar'))) openTask(task.dataset.taskId); return; }
  const question = event.target.closest('[data-question]');
  if (question) { focusAssistant(); sendChat(question.dataset.question); return; }
  const remove = event.target.closest('[data-remove-subtask]');
  if (remove) { checklist.splice(Number(remove.dataset.removeSubtask),1); renderChecklist(); return; }
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (action === 'focus-assistant') focusAssistant();
  if (action === 'ask-risks') { focusAssistant(); sendChat('Какие риски есть в проекте и что делать?'); }
  if (action === 'add-task') openTask();
  if (action === 'new-project') $('#btnNew').click();
  if (action === 'close-impact') { cancelImpactExplanation(); $('#impactCard').hidden = true; }
  if (action === 'apply-checklist') applyChecklist();
  if (!event.target.closest('#projectMenu')) $('#projectMenu').open = false;
});
document.addEventListener('contextmenu', event => {
  const task = event.target.closest('[data-task-id]');
  if (task) { event.preventDefault(); explainTask(task.dataset.taskId); }
});
document.addEventListener('keydown', async event => {
  if (event.key === 'Escape') closeNav();
  if (event.target.matches('.graph-node') && ['Enter',' '].includes(event.key)) { event.preventDefault(); openTask(event.target.dataset.taskId); }
  if (event.target.matches('.view-tab') && ['ArrowLeft','ArrowRight'].includes(event.key)) {
    event.preventDefault();
    const views = ['timeline','table','graph'], index = views.indexOf(state.view);
    if (await selectView(views[(index + (event.key === 'ArrowRight' ? 1 : 2)) % 3])) $(`#tab-${state.view}`).focus();
  }
});
$$('dialog').forEach(dialog => dialog.addEventListener('click', event => {
  const rect = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) && !taskBusy && !datesSaving && !creatingProject) dialog.close();
}));
$('#taskModal').addEventListener('cancel', event => { if (taskBusy) event.preventDefault(); });
$('#taskModal').addEventListener('close', () => { if (explanationTarget === 'preview') cancelImpactExplanation(); });
$('#menuToggle').onclick = () => { $('#sidebar').classList.add('open'); $('#navBackdrop').hidden = false; $('#menuToggle').setAttribute('aria-expanded','true'); };
$('#navBackdrop').onclick = closeNav;
$('#btnAssistant').onclick = () => {
  if ($('#assistantPanel').hidden) focusAssistant();
  else setAssistantOpen(false);
};
$('#btnCloseAssistant').onclick = () => { setAssistantOpen(false); $('#btnAssistant').focus(); };
$('#projectSel').onchange = () => busy(null, async () => {
  const pid = $('#projectSel').value;
  if (sandboxSession.dirty && !await confirmAction('Перейти в другой проект?', 'Пробные изменения текущего сценария будут сброшены.', 'Перейти')) {
    $('#projectSel').value = state.pid; return;
  }
  await openProject(pid);
});
$('#btnAddTask').onclick = () => openTask();
function validateDates(prefix) {
  const start = $(`#${prefix}Start`), deadline = $(`#${prefix}Deadline`);
  const range = dateRange(start.value,deadline.value,dateRules[prefix]);
  start.setCustomValidity(range.start.error);
  deadline.setCustomValidity(range.deadline.error);
  return range;
}
function setDate(prefix, field, iso) {
  setDateField($(`#${prefix}${field}`),$(`#${prefix}${field}Picker`),iso);
}
for (const prefix of ['p','d']) {
  for (const field of ['Start','Deadline']) bindDateField(
    $(`#${prefix}${field}`), $(`#${prefix}${field}Picker`), $(`#${prefix}${field}Open`),
    () => { $(`#${prefix}Start`).setCustomValidity(''); $(`#${prefix}Deadline`).setCustomValidity(''); });
}
for (const id of ['datesModal','projModal']) {
  $(`#${id}`).addEventListener('cancel', event => { if (datesSaving || creatingProject) event.preventDefault(); });
}
async function calendarOperation(formId, action) {
  const controls = $$(`#${formId} input, #${formId} textarea, #${formId} button`);
  controls.forEach(control => { control.disabled = true; });
  $(`#${formId}`).setAttribute('aria-busy','true');
  try { await action(); } catch (error) { toast(error.message, true); }
  finally {
    controls.forEach(control => { control.disabled = false; });
    $(`#${formId}`).removeAttribute('aria-busy');
  }
}
$('#btnNew').onclick = () => busy($('#btnNew'), async () => {
  const clock = await request('/api/calendar');
  dateRules.p = {today:clock.today}; $('#pStartPicker').min = clock.today; $('#pDeadlinePicker').min = clock.today;
  closeNav(); $('#projectForm').reset(); setDate('p','Start',clock.today);
  setDate('p','Deadline',null); $('#projModal').showModal(); $('#pName').focus();
});
$('#projectForm').onsubmit = async event => {
  event.preventDefault();
  const range = validateDates('p');
  if (creatingProject || !$('#projectForm').reportValidity()) return;
  const body = {name:$('#pName').value.trim(),description:$('#pDesc').value.trim(),
    start_date:range.start.iso,deadline_date:range.deadline.iso};
  creatingProject = true;
  try {
    await calendarOperation('projectForm', async () => {
      const data = await request('/api/projects', {method:'POST',body});
      $('#projModal').close(); await refreshProjects(data.project.id); toast('Проект создан. Добавьте первую задачу.');
    });
  } finally { creatingProject = false; }
};
$('#btnProjectDates').onclick = () => busy($('#btnProjectDates'), async () => {
  if (!state.project || state.loading || sandboxSession.active || taskBusy) return;
  const pid = state.pid, clock = await request('/api/calendar');
  if (state.pid !== pid || state.loading || sandboxSession.active) return;
  dateRules.d = {today:clock.today,existingStart:state.project.start_date};
  $('#dStartPicker').min = clock.today; $('#dDeadlinePicker').min = state.project.start_date || clock.today;
  cancelImpactExplanation(); $('#impactCard').hidden = true;
  dateEditing = {pid:state.pid,revision:state.revision};
  $('#datesForm').reset();
  setDate('d','Start',state.project.start_date);
  setDate('d','Deadline',state.project.deadline_date || state.analysis.calendar?.suggested_deadline_date);
  $('#datesModal').showModal(); $('#dStart').focus();
});
$('#datesForm').onsubmit = async event => {
  event.preventDefault(); const range = validateDates('d');
  if (datesSaving || !dateEditing || !$('#datesForm').reportValidity()) return;
  const current = {...dateEditing};
  const body = {start_date:range.start.iso,deadline_date:range.deadline.iso,base_revision:current.revision};
  datesSaving = true;
  try {
    await calendarOperation('datesForm', async () => {
      await request(projectPath(current.pid), {method:'PUT',body});
      $('#datesModal').close(); await openProject(current.pid); toast('Даты сохранены. План пересчитан.');
    });
  } finally { datesSaving = false; }
};
$('#btnDelProject').onclick = () => busy($('#btnDelProject'), async () => {
  const pid = state.pid; $('#projectMenu').open = false;
  if (!await confirmAction('Удалить проект?', `Проект «${state.project.name}» и все его задачи будут удалены.`)) return;
  await request(projectPath(pid), {method:'DELETE'}); histories.delete(pid); await refreshProjects(null); toast('Проект удалён');
});
$('#btnReset').onclick = () => busy($('#btnReset'), async () => {
  const pid = state.pid; $('#projectMenu').open = false;
  if (!await confirmAction('Восстановить демо?', 'Текущий проект будет заменён демонстрационным планом из 10 задач.', 'Восстановить')) return;
  await request(projectPath(pid, '/reset-demo'), {method:'POST',body:{}});
  histories.delete(pid); radarSignatures.delete(pid); $('#impactCard').hidden = true;
  await refreshProjects(pid); toast('Демонстрационный план восстановлен');
});
$('#taskForm').onsubmit = event => { event.preventDefault(); impact(true); };
$('#tmPreview').onclick = () => impact(false);
$('#tmDelete').onclick = deleteTask;
$('#tmExplain').onclick = () => explainTask(editing.id);
$('#tmChecklist').onclick = generateChecklist;
$('#fStatus').addEventListener('change', updateDurationLabel);
$('#taskForm').addEventListener('input', event => {
  cancelImpactExplanation();
  if (event.target.matches('[data-subtask]')) checklist[Number(event.target.dataset.subtask)].duration = Number(event.target.value);
  $('#taskPreview').innerHTML = previewPlaceholder;
});
$('#chatForm').onsubmit = event => { event.preventDefault(); sendChat($('#chatInput').value); };
$('#chatInput').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendChat(event.target.value); } };
$('#btnReport').onclick = () => busy($('#btnReport'), async () => {
  const pid = state.pid;
  const response = await fetch(projectPath(pid, '/report.md'));
  if (!response.ok) throw new Error('Не удалось сформировать отчёт');
  const text = await response.text();
  const ai = {source:response.headers.get('X-AI-Source'),model:response.headers.get('X-AI-Model'),reason:response.headers.get('X-AI-Reason')};
  addMessage(text, 'ai', pid, false, ai);
  const url = URL.createObjectURL(new Blob([text], {type:'text/markdown;charset=utf-8'}));
  const link = document.createElement('a'); link.href = url; link.download = `report-${pid}.md`; link.click();
  setTimeout(() => URL.revokeObjectURL(url),1000); toast('Отчёт подготовлен и скачан');
});

let checkingDay = false, warnedDay = null;
async function refreshCalendarDay() {
  if (checkingDay || document.hidden || state.loading || !state.analysis?.calendar?.configured) return;
  const pid = state.pid;
  checkingDay = true;
  try {
    const clock = await request('/api/calendar');
    if (pid !== state.pid || clock.today === state.analysis?.calendar?.today) return;
    if (taskBusy || datesSaving || creatingProject || sandboxSession.active || $$('dialog[open]').length) {
      if (warnedDay !== clock.today) {
        warnedDay = clock.today;
        toast('Наступил новый день. Закройте форму или выйдите из песочницы, чтобы обновить отметку «Сегодня».');
      }
      return;
    }
    await openProject(pid);
    toast('Текущий день проекта обновлён.');
  } catch { /* Retry after focus or on the next minute, preserving the open plan. */ }
  finally { checkingDay = false; }
}
window.addEventListener('focus', refreshCalendarDay);
document.addEventListener('visibilitychange', refreshCalendarDay);
setInterval(refreshCalendarDay, 60000);
$$('dialog').forEach(dialog => dialog.addEventListener('close', () => { void refreshCalendarDay(); }));

hydrateIcons();
refreshProjects().catch(error => {
  console.error('Project initialization failed', error);
  $('#saveState').textContent = 'Ошибка загрузки';
  $('#projectTitle').textContent = 'Не удалось загрузить проект';
  $('#projectDescription').hidden = false;
  $('#projectDescription').textContent = 'Обновите страницу. Если ошибка повторяется, попробуйте перезапустить приложение.';
  ['btnAddTask','btnSandbox','btnReport','btnSend'].forEach(id => { $(`#${id}`).disabled = true; });
  $('#chatInput').disabled = true;
  $('#badges').setAttribute('aria-busy','false');
  toast('Не удалось открыть проект. Попробуйте обновить страницу.',true);
});
