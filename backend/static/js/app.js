import {$, $$, escapeHTML as esc, icon, hydrateIcons, richText, toast, busy, confirmAction, aiNotice} from './ui.js';
import {request, projectPath} from './api.js';
import {renderProject, renderTimeline, timelineScale, impactMarkup, renderSandbox, renderRadar} from './views.js';

const state = {pid:null, project:null, analysis:null, owners:[], view:'timeline', sandbox:false, sandboxState:null};
const histories = new Map(), pendingChats = new Set(), radarSignatures = new Map();
let loadVersion = 0, sandboxVersion = 0, editing = null, checklist = [], taskBusy = false;
const previewPlaceholder = `<div class="preview-empty">${icon('branches')}<h3>Сначала оцените последствия</h3><p>Узнайте, как изменение повлияет на сроки и связанные задачи, перед сохранением.</p></div>`;
const history = pid => { if (!histories.has(pid)) histories.set(pid, []); return histories.get(pid); };

function renderMessages() {
  const messages = state.pid ? history(state.pid) : [];
  $('#messages').innerHTML = messages.map(item => `<article class="message ${item.role}${item.auto ? ' auto' : ''}">${item.role === 'ai' ? `<div class="message-label">${icon(item.auto ? 'radar' : 'sparkles')}${item.auto ? 'Радар проекта' : 'PM Radar'}</div>` : ''}<div class="message-body">${aiNotice(item)}${richText(item.text)}</div></article>`).join('') + (pendingChats.has(state.pid) ? '<div class="typing-dots" role="status" aria-label="Ассистент готовит ответ"><i></i><i></i><i></i></div>' : '');
  const latest = $('#messages').lastElementChild;
  if (latest) $('#messages').scrollTop += latest.getBoundingClientRect().top - $('#messages').getBoundingClientRect().top - 18;
  $('#btnSend').disabled = !state.pid || pendingChats.has(state.pid);
}
function updateAI(ai) {
  if (!ai || ai.source === 'pending') return;
  $('#aiStatus').textContent = ai.source === 'llm' ? 'DeepSeek V4.1 Flash · подключён' : 'Резервный режим · без нейросети';
  $('#aiStatus').title = ai.message || ai.model || '';
  $('#aiBadge').textContent = ai.source === 'llm' ? 'LLM' : 'Локально';
}
function addMessage(text, role = 'ai', pid = state.pid, auto = false, ai = null) {
  history(pid).push({text, role, auto, ai});
  if (pid === state.pid) updateAI(ai);
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
    clearSandbox(); renderProject(state); quickPrompts(); renderMessages();
    $('#radarSummary').innerHTML = `<span class="radar-orbit">${icon('folder')}</span><div><strong>Создайте первый проект</strong><p>Ассистент подключится к вашему плану</p></div>`;
    $('#impactCard').hidden = true;
    $('#saveState').innerHTML = '<i></i>Всё сохранено';
  }
}
async function openProject(pid) {
  const version = ++loadVersion;
  $('#saveState').textContent = 'Загрузка…';
  const payload = await request(projectPath(pid));
  if (version !== loadVersion) return;
  const changed = state.pid !== pid;
  Object.assign(state, payload, {pid});
  clearSandbox();
  if (changed) { $('#impactCard').hidden = true; $('#chatInput').value = ''; }
  renderProject(state); quickPrompts();
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
    updateAI(radar.ai);
    if (radarSignatures.get(pid) !== signature) {
      addMessage(radar.text, 'ai', pid, true, radar.ai);
    }
    radarSignatures.set(pid, signature);
  } catch (error) { toast(`Радар: ${error.message}`, true); }
}
function selectView(view) {
  state.view = view;
  $$('[data-view-panel]').forEach(panel => { panel.hidden = panel.dataset.viewPanel !== view; });
  $$('[data-view]').forEach(button => {
    const active = button.dataset.view === view;
    button.classList.toggle('active', active);
    if (button.getAttribute('role') === 'tab') { button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1; }
    if (button.classList.contains('nav-item')) { if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current'); }
  });
  $('#breadcrumbView').textContent = {timeline:'Обзор проекта',table:'Все задачи',graph:'Зависимости'}[view];
  closeNav();
}
function closeNav() { $('#sidebar').classList.remove('open'); $('#navBackdrop').hidden = true; $('#menuToggle').setAttribute('aria-expanded','false'); }
function focusAssistant() { closeNav(); $('#assistantPanel').scrollIntoView({behavior:'smooth',block:'nearest'}); $('#chatInput').focus({preventScroll:true}); }
async function sendChat(text) {
  const pid = state.pid;
  if (!pid || !text.trim() || pendingChats.has(pid)) return;
  pendingChats.add(pid); addMessage(text.trim(), 'user', pid);
  $('#chatInput').value = '';
  try {
    const data = await request(projectPath(pid, '/assistant'), {method:'POST',body:{message:text.trim()}});
    addMessage(data.reply, 'ai', pid, false, data.ai);
  } catch (error) { addMessage(`Не удалось получить ответ: ${error.message}. Попробуйте отправить вопрос ещё раз.`, 'ai', pid); }
  finally { pendingChats.delete(pid); if (state.pid === pid) renderMessages(); }
}

function openTask(id) {
  if (!state.project || taskBusy) return;
  const task = state.project.tasks.find(t => t.id === id);
  editing = {pid:state.pid, id:task?.id || `task-${crypto.randomUUID()}`, existing:Boolean(task)};
  checklist = [];
  $('#taskForm').reset();
  $('#tmTitle').textContent = task ? 'Редактировать задачу' : 'Новая задача';
  $('#fName').value = task?.name || '';
  $('#fDur').value = task?.duration ?? 5;
  $('#fOwner').value = task?.owner || '';
  $('#fStatus').value = task?.status || 'todo';
  $('#fDeps').innerHTML = state.project.tasks.filter(t => t.id !== task?.id).map(t => `<label class="dependency-choice"><input type="checkbox" value="${esc(t.id)}" ${task?.dependencies.includes(t.id) ? 'checked' : ''}><span>${esc(t.name)}</span></label>`).join('') || '<p class="field-hint">Других задач пока нет</p>';
  $('#tmDelete').hidden = !task; $('#tmExplain').hidden = !task;
  $('#clBox').innerHTML = ''; $('#clNote').textContent = '';
  $('#taskPreview').innerHTML = previewPlaceholder;
  $('#taskModal').showModal(); $('#fName').focus();
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
  if (!$('#taskForm').reportValidity()) return;
  const task = formTask(), current = {...editing};
  if (!task.name) { toast('Введите название задачи', true); return; }
  return taskOperation(async () => {
    const body = {task_id:task.id,changes:task,apply:applied};
    if (!current.existing) body.tasks = [...state.project.tasks, task];
    const data = await request(projectPath(current.pid, '/impact'), {method:'POST',body});
    if (!applied) { $('#taskPreview').innerHTML = impactMarkup(data); return; }
    $('#taskModal').close();
    await refreshProjects(current.pid);
    showImpact(data); addMessage(data.explanation, 'ai', current.pid, false, data.ai);
    toast('Задача сохранена. План пересчитан.');
  });
}
function showImpact(data) { $('#impact').innerHTML = impactMarkup(data); $('#impactCard').hidden = false; }
async function deleteTask() {
  const current = {...editing};
  if (!await confirmAction('Удалить задачу?', 'Задача будет удалена из плана и зависимостей других задач.')) return;
  await taskOperation(async () => {
    const tasks = state.project.tasks.filter(t => t.id !== current.id).map(t => ({...t, dependencies:t.dependencies.filter(id => id !== current.id)}));
    await request(projectPath(current.pid), {method:'PUT',body:{tasks}});
    $('#taskModal').close(); $('#impactCard').hidden = true;
    await refreshProjects(current.pid); toast('Задача удалена. План пересчитан.');
  });
}
async function explainTask(id) {
  const pid = state.pid;
  $('#exTitle').textContent = state.project.tasks.find(t => t.id === id)?.name || 'Объяснение задачи';
  $('#exText').textContent = 'Разбираю связи и последствия…';
  if (!$('#explainModal').open) $('#explainModal').showModal();
  await busy(null, async () => {
    const data = await request(projectPath(pid, `/explain/${encodeURIComponent(id)}`));
    $('#exText').innerHTML = aiNotice(data) + richText(data.explanation); updateAI(data.ai);
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
    if (editing !== current || !$('#taskModal').open) return;
    checklist = data.suggestion.subtasks;
    $('#clNote').innerHTML = aiNotice(data) + esc(data.suggestion.note || 'Проверьте подзадачи и их длительность.'); updateAI(data.ai);
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
      await request(projectPath(current.pid), {method:'PUT',body:{tasks}});
    } else await request(projectPath(current.pid, '/apply-checklist'), {method:'POST',body:{subtasks:subs}});
    $('#taskModal').close(); $('#impactCard').hidden = true;
    await refreshProjects(current.pid); toast('Подзадачи добавлены. Зависимости обновлены.');
  });
}

function clearSandbox() {
  ++sandboxVersion; state.sandboxState = null; $('#sandboxCard').hidden = true;
  $('#tlHint').textContent = state.sandbox ? 'Потяните полосу задачи, чтобы сдвинуть её начало. Или используйте ← → на выбранной полосе.' : 'Нажмите на задачу, чтобы увидеть детали и изменить план.';
}
async function simulate(taskId, shift) {
  const version = ++sandboxVersion, pid = state.pid;
  state.sandboxState = null; $('#sandboxCard').hidden = true;
  if (!shift) { renderTimeline(state); return; }
  $('#tlHint').textContent = 'Рассчитываю последствия…';
  try {
    const body = {task_id:taskId,shift_days:shift};
    const data = await request(projectPath(pid, '/sandbox'), {method:'POST',body:{...body,explain:false}});
    if (version !== sandboxVersion || pid !== state.pid) return;
    state.sandboxState = {pid,taskId,shift};
    const bar = $$('#timeline .gantt-bar').find(item => item.dataset.taskId === taskId);
    if (bar) {
      bar.style.left = `${Number(bar.dataset.originalLeft) + shift / timelineScale(state).maxDay * 100}%`;
    }
    renderSandbox(data);
    $('#tlHint').textContent = 'Сценарий рассчитан. Результат под графиком; исходный план ещё не изменён.';
    $('#sandboxCard').scrollIntoView({behavior:'smooth',block:'nearest'});
    const narrated = await request(projectPath(pid, '/sandbox'), {method:'POST',body});
    if (version !== sandboxVersion || pid !== state.pid) return;
    renderSandbox(narrated); addMessage(narrated.explanation, 'ai', pid, false, narrated.ai);
  } catch (error) { if (version === sandboxVersion) { renderTimeline(state); toast(error.message, true); } }
}
let drag = null;
$('#timeline').addEventListener('pointerdown', event => {
  const bar = event.target.closest('.gantt-bar');
  if (!state.sandbox || !bar || bar.classList.contains('done') || event.button !== 0) return;
  event.preventDefault();
  clearSandbox();
  renderTimeline(state);
  const active = $$('#timeline .gantt-bar').find(item => item.dataset.taskId === bar.dataset.taskId);
  const width = active.parentElement.getBoundingClientRect().width;
  drag = {bar:active,id:active.dataset.taskId,start:event.clientX,delay:Number(active.dataset.startDelay),shift:0,pixels:width / timelineScale(state).maxDay,original:Number(active.dataset.originalLeft),trackWidth:width};
  active.classList.add('dragging');
  $('#timeline').setPointerCapture(event.pointerId);
});
$('#timeline').addEventListener('pointermove', event => {
  if (!drag) return;
  drag.shift = Math.max(-drag.delay, Math.round((event.clientX - drag.start) / drag.pixels));
  drag.bar.style.left = `${drag.original + drag.shift * drag.pixels / drag.trackWidth * 100}%`;
});
$('#timeline').addEventListener('pointerup', () => {
  if (!drag) return;
  const {id,shift,bar} = drag; drag = null; bar.classList.remove('dragging'); simulate(id,shift);
});
$('#timeline').addEventListener('pointercancel', () => { drag = null; clearSandbox(); renderTimeline(state); });
$('#timeline').addEventListener('keydown', event => {
  const bar = event.target.closest('.gantt-bar');
  if (!state.sandbox || !bar || bar.classList.contains('done') || !['ArrowLeft','ArrowRight'].includes(event.key)) return;
  event.preventDefault();
  const previous = state.sandboxState?.taskId === bar.dataset.taskId ? state.sandboxState.shift : 0;
  simulate(bar.dataset.taskId, Math.max(-Number(bar.dataset.startDelay),previous + (event.key === 'ArrowRight' ? 1 : -1)));
});
$('#btnSandbox').onclick = () => {
  state.sandbox = !state.sandbox; clearSandbox(); renderTimeline(state);
  $('#btnSandbox').setAttribute('aria-pressed',String(state.sandbox));
  $('#tlHint').textContent = state.sandbox ? 'Потяните полосу задачи, чтобы сдвинуть её начало. Или используйте ← → на выбранной полосе.' : 'Нажмите на задачу, чтобы увидеть детали и изменить план.';
};
$('#sbReset').onclick = () => { clearSandbox(); renderTimeline(state); $('#tlHint').textContent = 'Сценарий сброшен. Потяните полосу, чтобы проверить новый вариант.'; };
$('#sbApply').onclick = () => busy($('#sbApply'), async () => {
  const scenario = state.sandboxState;
  if (!scenario) return;
  const task = state.project.tasks.find(t => t.id === scenario.taskId);
  const data = await request(projectPath(scenario.pid, '/impact'), {method:'POST',body:{task_id:task.id,changes:{start_delay:(task.start_delay || 0) + scenario.shift},apply:true}});
  await openProject(scenario.pid); showImpact(data); addMessage(data.explanation, 'ai', scenario.pid, false, data.ai); toast('Изменение применено');
});

document.addEventListener('click', event => {
  const view = event.target.closest('[data-view]');
  if (view) { event.preventDefault(); selectView(view.dataset.view); return; }
  const close = event.target.closest('[data-close]');
  if (close) { document.getElementById(close.dataset.close).close(); return; }
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
  if (action === 'close-impact') $('#impactCard').hidden = true;
  if (action === 'apply-checklist') applyChecklist();
  if (!event.target.closest('#projectMenu')) $('#projectMenu').open = false;
});
document.addEventListener('contextmenu', event => {
  const task = event.target.closest('[data-task-id]');
  if (task) { event.preventDefault(); explainTask(task.dataset.taskId); }
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeNav();
  if (event.target.matches('.graph-node') && ['Enter',' '].includes(event.key)) { event.preventDefault(); openTask(event.target.dataset.taskId); }
  if (event.target.matches('.view-tab') && ['ArrowLeft','ArrowRight'].includes(event.key)) {
    event.preventDefault();
    const views = ['timeline','table','graph'], index = views.indexOf(state.view);
    selectView(views[(index + (event.key === 'ArrowRight' ? 1 : 2)) % 3]); $(`#tab-${state.view}`).focus();
  }
});
$$('dialog').forEach(dialog => dialog.addEventListener('click', event => {
  const rect = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) && !taskBusy) dialog.close();
}));
$('#taskModal').addEventListener('cancel', event => { if (taskBusy) event.preventDefault(); });
$('#menuToggle').onclick = () => { $('#sidebar').classList.add('open'); $('#navBackdrop').hidden = false; $('#menuToggle').setAttribute('aria-expanded','true'); };
$('#navBackdrop').onclick = closeNav;
$('#projectSel').onchange = () => busy(null, () => openProject($('#projectSel').value));
$('#btnAddTask').onclick = () => openTask();
$('#btnNew').onclick = () => { closeNav(); $('#projectForm').reset(); $('#projModal').showModal(); $('#pName').focus(); };
$('#projectForm').onsubmit = event => {
  event.preventDefault();
  busy($('#pmCreate'), async () => {
    const name = $('#pName').value.trim();
    if (!name) throw new Error('Введите название проекта');
    const data = await request('/api/projects', {method:'POST',body:{name,description:$('#pDesc').value.trim(),deadline:$('#pDeadline').value ? Number($('#pDeadline').value) : null}});
    $('#projModal').close(); await refreshProjects(data.project.id); toast('Проект создан. Добавьте первую задачу.');
  });
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
$('#taskForm').addEventListener('input', event => {
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

hydrateIcons();
request('/api/ai/status').then(ai => {
  $('#aiStatus').textContent = ai.configured ? 'DeepSeek V4.1 Flash · настроен' : 'Расчётный движок · без нейросети';
  $('#aiBadge').textContent = ai.configured ? 'LLM' : 'Локально';
}).catch(() => { $('#aiStatus').textContent = 'Статус ИИ недоступен'; });
refreshProjects().catch(error => { $('#saveState').textContent = 'Нет соединения'; $('#projectTitle').textContent = 'Не удалось загрузить проект'; $('#projectDescription').textContent = 'Убедитесь, что PM Radar запущен, и обновите страницу.'; toast(error.message,true); });
