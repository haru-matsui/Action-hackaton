import {$, escapeHTML as esc, icon, avatar, statusPill, statusNames, richText, emptyState, signed, plural, aiNotice} from './ui.js';
import {dateText, projectDay, taskPeriod} from './dates.js';

export function renderProject(state) {
  const project = state.project;
  const calendar = state.analysis?.calendar;
  const dated = Boolean(calendar?.configured);
  const tasks = state.analysis?.tasks || [];
  const summary = state.analysis?.summary;
  const progress = summary?.progress;
  const done = progress?.done_count || 0;
  const active = progress?.in_progress_count || 0;
  const percent = progress?.completion_percent_by_task_count || 0;
  $('#projectTitle').textContent = project?.name || 'Начните с первого проекта';
  $('#projectDescription').textContent = project?.description || (project ? '' : 'Создайте проект, добавьте задачи и соберите понятный план действий.');
  $('#projectDescription').hidden = Boolean(project) && !project.description;
  $('#projectCalendar').hidden = !project;
  $('#calendarSummary').innerHTML = dated ? `<span>Начало ${dateText(calendar.start_date)}</span><span class="current-project-day">${projectDay(calendar)}</span><span>Сегодня ${dateText(calendar.today)}</span>` : '<span>Дата начала не указана</span>';
  $('#calendarAction').textContent = dated ? 'Изменить даты' : 'Указать даты';
  $('#planUnits').innerHTML = `${icon('calendar')}${dated ? 'Пн–Пт' : 'Рабочие дни'}`;
  $('#planUnits').title = dated ? 'Календарь рабочих дней. Выходные пропускаются. Праздничные будни считаются рабочими.' : 'Укажите даты проекта, чтобы перейти на календарную шкалу.';
  document.title = `${project?.name || 'Мои проекты'} · PM Radar`;
  $('#teamAvatars').innerHTML = (state.owners || []).slice(0, 5).map(avatar).join('');
  $('#taskCount').textContent = tasks.length;
  $('#sidePercent').textContent = `${percent}%`;
  $('#sideProgress').style.width = `${percent}%`;
  $('#sideProgressText').textContent = `${done} из ${tasks.length} задач выполнено`;
  ['btnAddTask','btnReset','btnDelProject','btnReport','btnSend'].forEach(id => { $(`#${id}`).disabled = !project; });
  $('#btnSandbox').disabled = !tasks.length;
  $('#chatInput').disabled = !project;
  $('#ownerList').innerHTML = (state.owners || []).map(owner => `<option value="${esc(owner)}"></option>`).join('');
  const deadline = summary?.project_deadline;
  const duration = summary?.project_duration || 0;
  const critical = summary?.critical_tasks.length || 0;
  const atRisk = summary?.at_risk.length || 0;
  const reserve = deadline == null || !tasks.some(t => t.status !== 'done') ? null : summary.deadline_reserve ?? deadline - duration;
  const forecast = dated ? `<b class="metric-date">${dateText(summary.forecast_finish_date, true)}</b>` : `<b>${duration}</b><span>${deadline == null ? 'дней' : `/ ${deadline} дн.`}</span>`;
  const deadlineNote = reserve == null ? 'Дедлайн не установлен' : reserve < 0 ? `На ${-reserve} дн. позже дедлайна` : `В запасе ${reserve} раб. дн.`;
  $('#badges').innerHTML = `
    <article class="metric ${reserve != null && reserve <= 2 ? 'amber' : ''}"><div class="metric-title">${dated ? 'Срок по плану' : 'Прогноз завершения'}${icon('clock')}</div><div class="metric-value">${forecast}</div><div class="mini-meter"><span style="width:${deadline > 0 ? Math.min(100, duration / deadline * 100) : 0}%"></span></div><div class="metric-note">${dated ? (summary.forecast_finish_date ? `Осталось ${duration} раб. дн.` : 'Нет незавершённых задач') + `<br>${calendar.deadline_date ? `Дедлайн ${dateText(calendar.deadline_date)}` : 'Дедлайн не установлен'}` : deadlineNote}</div></article>
    <article class="metric"><div class="metric-title">Выполнено задач${icon('checkCircle')}</div><div class="metric-value"><b>${done}</b><span>/ ${tasks.length}</span></div><div class="mini-meter"><span class="segment-done" style="width:${percent}%"></span><span class="segment-active" style="width:${tasks.length ? active / tasks.length * 100 : 0}%"></span></div><div class="metric-note">${percent}% задач завершено</div></article>
    <article class="metric violet"><div class="metric-title">Критический путь${icon('route')}</div><div class="metric-value"><b>${critical}</b><span>${plural(critical, 'задача', 'задачи', 'задач')}</span></div><div class="mini-chain" aria-hidden="true">${Array.from({length:Math.min(critical, 8)}, () => '<i></i>').join('')}</div><div class="metric-note">Определяют общий срок</div></article>
    <article class="metric amber"><div class="metric-title">Под угрозой${icon('flag')}</div><div class="metric-value"><b>${atRisk}</b><span>${plural(atRisk, 'задача', 'задачи', 'задач')}</span></div><div class="mini-risks" aria-hidden="true">${tasks.slice(0, 14).map(task => `<i class="${summary?.at_risk.includes(task.id) ? 'risk' : ''}"></i>`).join('')}</div><div class="metric-note">${atRisk ? 'Нуждаются во внимании' : 'Риски не обнаружены'}</div></article>`;
  $('#badges').setAttribute('aria-busy', 'false');
  const alert = $('#projectAlert');
  alert.hidden = !tasks.length;
  alert.className = `attention-banner ${summary?.deadline_breached ? 'danger' : atRisk ? '' : 'good'}`;
  let heading, note;
  if (summary?.status_conflicts?.length) {
    heading = 'Статусы задач противоречат зависимостям';
    note = 'Проверьте связи начатых и завершённых задач. Прогноз требует уточнения.';
    alert.className = 'attention-banner';
  } else if (summary?.deadline_breached) {
    heading = `Прогноз превышает дедлайн на ${summary.delay_vs_deadline} дн.`;
    note = 'Проверьте критические задачи и возможные варианты действий.';
  } else if (reserve != null && reserve <= 2) {
    heading = `До дедлайна — ${reserve} ${reserve === 1 ? 'день резерва' : 'дн. резерва'}`;
    note = 'Задержка на критическом пути может сдвинуть срок проекта.';
  } else if (atRisk) {
    heading = `${atRisk} ${plural(atRisk, 'задача требует', 'задачи требуют', 'задач требуют')} внимания`;
    note = 'Проверьте задачи с минимальным запасом времени.';
  } else {
    heading = 'План выглядит устойчиво';
    note = 'Измените задачу, чтобы оценить последствия для проекта.';
  }
  alert.innerHTML = `${icon(atRisk || summary?.deadline_breached ? 'alert' : 'checkCircle')}<div><strong>${heading}</strong><p>${note}</p></div><button class="text-button" data-action="ask-risks">Разобрать${icon('arrowUpRight')}</button>`;
  renderTimeline(state);
  renderTable(state);
  renderGraph(state);
  renderPath(state);
}

export function timelineScale(state) {
  const calendar = state.analysis?.calendar;
  if (calendar?.configured) {
    const base = state.baselineAnalysis?.calendar;
    const scale = base?.max_day > calendar.max_day ? base : calendar;
    return {maxDay:scale.max_day, step:scale.step, percent:day => day / scale.max_day * 100, ticks:scale.ticks};
  }
  const summary = state.analysis?.summary;
  const horizon = Math.max(summary?.project_duration || 0, summary?.project_deadline || 0,
    state.baselineAnalysis?.summary.project_duration || 0, 1);
  const maxDay = horizon + Math.max(2, Math.ceil(horizon * .08));
  const step = Math.max(1, Math.ceil(horizon / 6 / 5) * 5);
  return {maxDay, step, percent: day => day / maxDay * 100};
}

export function renderTimeline(state) {
  const tasks = state.analysis?.tasks || [];
  const calendar = state.analysis?.calendar;
  const dated = Boolean(calendar?.configured);
  const baseline = new Map((state.baselineAnalysis?.tasks || []).map(task => [task.id, task]));
  $('#timeline').classList.toggle('calendar-timeline', dated);
  $('#timeline').classList.toggle('sandbox-mode', state.sandbox);
  $('#timeline').style.minWidth = '';
  if (!tasks.length) {
    $('#timeline').innerHTML = emptyState('У хорошего плана есть начало', 'Добавьте первую задачу и назначьте ответственного.', `<button class="button primary" data-action="${state.project ? 'add-task' : 'new-project'}">${icon('plus')}${state.project ? 'Добавить задачу' : 'Создать проект'}</button>`);
    return;
  }
  const {maxDay, step, percent, ticks:calendarTicks} = timelineScale(state);
  const deadline = dated ? calendar.deadline_offset : state.analysis.summary.project_deadline;
  const deadlineVisible = deadline != null && deadline >= 0 && deadline <= maxDay;
  const ticks = [];
  const tickData = dated ? calendarTicks : Array.from({length:Math.floor(maxDay / step)+1}, (_,i) => ({offset:i*step}));
  if (dated) $('#timeline').style.minWidth = `calc(var(--meta-width) + ${Math.min(2800, Math.max(500, maxDay * 22))}px)`;
  for (const tick of tickData) {
    if (dated && tick.offset > maxDay - step * .5) continue;
    if (!dated && deadlineVisible && Math.abs(tick.offset - deadline) < step * .65) continue;
    ticks.push(`<span class="gantt-tick" style="left:${percent(tick.offset)}%">${dated ? dateText(tick.date) : tick.offset}</span>`);
  }
  const today = dated ? `<span class="today-label" style="left:${percent(calendar.today_offset)}%;transform:translateX(${percent(calendar.today_offset) > 60 ? '-100%' : '0'})">Сегодня · ${dateText(calendar.today)}</span>` : '';
  const deadlinePosition = deadlineVisible ? percent(deadline) : null;
  const deadlineEdge = dated && deadlineVisible ? (deadlinePosition < 20 ? ' edge-start' : deadlinePosition > 80 ? ' edge-end' : '') : '';
  const axis = `<div class="gantt-axis"><div class="gantt-axis-label">ЗАДАЧА / ОТВЕТСТВЕННЫЙ</div><div class="gantt-axis-track">${ticks.join('')}${today}${deadlineVisible ? `<span class="deadline-label${deadlineEdge}" style="left:${deadlinePosition}%">Дедлайн · ${dated ? dateText(calendar.deadline_date) : deadline}</span>${dated ? `<span class="deadline-axis-mark" style="left:${deadlinePosition}%" aria-hidden="true"></span>` : ''}` : ''}</div></div>`;
  const startOf = task => dated ? task.calendar_start_offset ?? calendar.planning_offset : task.early_start;
  $('#timeline').innerHTML = axis + tasks.map(task => {
    const width = Math.max(percent(task.early_finish - task.early_start), 1);
    const start = startOf(task);
    const risk = state.analysis.summary.at_risk.includes(task.id);
    const old = baseline.get(task.id);
    const moved = state.sandbox && old && old.early_start !== task.early_start;
    const ghost = moved ? `<span class="gantt-baseline" style="left:${percent(startOf(old))}%;width:${Math.max(percent(old.early_finish - old.early_start),1)}%" aria-hidden="true"></span>` : '';
    const locked = state.sandbox && task.status !== 'todo';
    const title = (task.status === 'done' ? `${task.name} — выполнена. Дата завершения не записана.` : `${task.name}: ${dated ? taskPeriod(task) : `дни ${task.early_start}–${task.early_finish}`}, резерв ${task.slack} дн.`) + (locked ? ' Начало этой задачи нельзя сдвинуть.' : state.sandbox ? '. Перетащите или используйте стрелки влево и вправо.' : '');
    const bar = dated && task.status === 'done' ? `<span class="gantt-completed" title="${esc(title)}">Выполнено</span>` : `<button class="gantt-bar ${task.status} ${task.is_critical ? 'critical' : ''} ${risk ? 'at-risk' : ''}" data-task-id="${esc(task.id)}" data-status="${task.status}" data-start="${task.early_start}" data-duration="${task.duration}" data-original-width="${width}" data-original-left="${percent(start)}" data-start-delay="${task.start_delay || 0}" style="left:${percent(start)}%;width:${width}%" title="${esc(title)}" aria-label="${esc(title)}" ${locked ? 'aria-disabled="true"' : ''}>${task.status === 'done' ? icon('check') : `<span class="bar-label">${task.early_finish - task.early_start}</span><span class="bar-grip"></span>`}</button>`;
    return `<div class="gantt-row ${moved ? 'scenario-moved' : ''}"><div class="gantt-meta"><span class="gantt-status ${task.status}" title="${statusNames[task.status]}">${task.status === 'done' ? icon('check') : ''}</span><div class="gantt-task-info"><button class="task-name" data-task-id="${esc(task.id)}" title="${esc(task.name)}">${esc(task.name)}</button><span class="gantt-owner">${esc(task.owner || 'Не назначен')}</span></div></div><div class="gantt-track" style="--tick-width:${percent(step)}%">${deadlineVisible ? `<div class="gantt-deadline" style="left:${percent(deadline)}%"></div>` : ''}${dated ? `<div class="gantt-today" style="left:${percent(calendar.today_offset)}%" aria-hidden="true"></div>` : ''}${ghost}${bar}</div></div>`;
  }).join('');
}

function renderTable(state) {
  const tasks = state.analysis?.tasks || [];
  $('#taskTable').innerHTML = `<thead><tr><th scope="col">Задача</th><th scope="col">Ответственный</th><th scope="col">Статус</th><th scope="col">Осталось</th><th scope="col">Резерв</th><th scope="col">Зависит от</th><th scope="col"><span class="sr-only">Действия</span></th></tr></thead><tbody>${tasks.map((task, index) => `<tr><td><div class="table-task"><span class="task-number">${String(index + 1).padStart(2, '0')}</span><div><button class="task-name" data-task-id="${esc(task.id)}">${esc(task.name)}</button><span class="table-period">${taskPeriod(task)}</span></div></div></td><td><div class="owner-cell">${avatar(task.owner || 'Не назначен')}<span>${esc(task.owner || 'Не назначен')}</span></div></td><td>${statusPill(task.status)}</td><td>${task.remaining_duration ?? (task.status === 'done' ? 0 : task.duration)} дн.</td><td class="${task.at_risk ? 'slack-critical' : ''}">${task.slack} дн.</td><td class="dependency-names">${task.dependencies.map(id => esc(tasks.find(item => item.id === id)?.name || id)).join(', ') || '—'}</td><td><button class="icon-button" data-explain="${esc(task.id)}" title="Объяснить задачу" aria-label="Объяснить задачу ${esc(task.name)}">${icon('sparkles')}</button></td></tr>`).join('') || '<tr><td colspan="7">Добавьте задачи, чтобы увидеть расчётный план.</td></tr>'}</tbody>`;
}

function wrapName(name) {
  const words = name.split(/\s+/), lines = [''];
  for (const word of words) {
    const index = lines.length - 1;
    if ((lines[index] + ' ' + word).trim().length > 26 && lines[index] && lines.length < 2) lines.push(word);
    else lines[index] = (lines[index] + ' ' + word).trim();
  }
  return lines.map(line => line.length > 27 ? line.slice(0, 25) + '…' : line);
}

function renderGraph(state) {
  const svg = $('#graph');
  const tasks = state.analysis?.tasks || [];
  if (!tasks.length) { svg.innerHTML = ''; svg.setAttribute('height', '100'); return; }
  const byId = Object.fromEntries(tasks.map(task => [task.id, task]));
  const levels = {};
  const depth = id => {
    if (id in levels) return levels[id];
    const predecessors = byId[id].dependencies.filter(parent => byId[parent]);
    levels[id] = predecessors.length ? 1 + Math.max(...predecessors.map(depth)) : 0;
    return levels[id];
  };
  const rows = {};
  tasks.forEach(task => (rows[depth(task.id)] ||= []).push(task));
  const nodeWidth = 198, nodeHeight = 74, gap = 18, rowHeight = 122;
  const width = Math.max(640, Math.max(...Object.values(rows).map(row => row.length)) * (nodeWidth + gap) + 30);
  const height = Object.keys(rows).length * rowHeight + 18;
  const positions = {};
  Object.entries(rows).forEach(([level, row]) => {
    const left = (width - row.length * (nodeWidth + gap) + gap) / 2;
    row.forEach((task, index) => { positions[task.id] = {x: left + index * (nodeWidth + gap), y: 24 + Number(level) * rowHeight}; });
  });
  const criticalEdges = new Set(state.analysis.summary.critical_edges.map(([from, to]) => `${from}→${to}`));
  let edges = '';
  for (const task of tasks) for (const parent of task.dependencies) {
    if (!positions[parent]) continue;
    const from = positions[parent], to = positions[task.id];
    const x1 = from.x + nodeWidth / 2, y1 = from.y + nodeHeight, x2 = to.x + nodeWidth / 2, y2 = to.y;
    const isCritical = criticalEdges.has(`${parent}→${task.id}`);
    edges += `<path class="graph-edge ${isCritical ? 'critical' : ''}" d="M${x1} ${y1} C${x1} ${y1+24} ${x2} ${y2-24} ${x2} ${y2-4}" marker-end="url(#${isCritical ? 'criticalArrow' : 'normalArrow'})"/>`;
  }
  const nodes = tasks.map(task => {
    const pos = positions[task.id], lines = wrapName(task.name);
    return `<g class="graph-node ${task.is_critical ? 'critical' : ''} ${task.status}" transform="translate(${pos.x},${pos.y})" data-task-id="${esc(task.id)}" role="button" tabindex="0" aria-label="${esc(task.name)}"><title>${esc(task.name)} · ${esc(task.owner || 'Не назначен')}</title><rect width="${nodeWidth}" height="${nodeHeight}" rx="1"/><circle class="graph-status" cx="${nodeWidth-13}" cy="17" r="3"/>${lines.map((line, i) => `<text class="node-title" x="13" y="${lines.length === 1 ? 28 : 22 + i*15}">${esc(line)}</text>`).join('')}<text class="node-meta" x="13" y="59">${task.status === 'done' ? 'Выполнено' : `${task.duration} дн. · резерв ${task.slack} дн.`}</text></g>`;
  }).join('');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('width', width);
  svg.setAttribute('height', height);
  svg.innerHTML = `<defs><marker id="normalArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10Z" class="graph-arrow"/></marker><marker id="criticalArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10Z" class="graph-arrow"/></marker></defs>${edges}${nodes}`;
}

function renderPath(state) {
  const tasks = state.analysis?.tasks || [];
  const summary = state.analysis?.summary;
  const branched = summary?.critical_branching;
  const path = (branched ? summary.critical_tasks : summary?.critical_path) || [];
  $('#criticalTitle').textContent = branched ? 'Критические ветки' : 'Критический путь';
  $('#criticalHint').textContent = branched ? 'Все эти задачи влияют на срок проекта. Связи между ветками показаны на вкладке «Зависимости».' : 'Эти задачи определяют срок завершения проекта.';
  $('#pathDuration').textContent = tasks.length ? `${state.analysis.summary.project_duration} рабочих дней` : '';
  $('#criticalPath').innerHTML = path.map(id => {
    const task = tasks.find(item => item.id === id);
    return `<button class="path-node ${task.status === 'done' ? 'done' : ''}" data-task-id="${esc(id)}">${task.status === 'done' ? icon('check') : ''}${esc(task.name)}</button>`;
  }).join(branched ? '' : icon('arrowRight', 'path-arrow')) || '<span class="field-hint">Путь появится, когда в проекте будут задачи.</span>';
}

function taskChangesMarkup(items, data) {
  const labels = {name:'Название', duration:'Оценка', start_delay:'Ожидание', status:'Статус',
    owner:'Ответственный', dependencies:'Предшественники', early_start:'Начало',
    early_finish:'Окончание', remaining_duration:'Осталось', slack:'Резерв',
    is_critical:'Критический путь', at_risk:'Под угрозой', planned_start_date:'Начало', planned_finish_date:'Окончание'};
  const format = (field, value, before) => {
    if (value == null) return '—';
    if (field === 'dependencies') return value.map(id =>
      (before ? data.before?.tasks : data.after.tasks)?.find(t => t.id === id)?.name || id).join(', ') || 'Нет';
    if (field === 'planned_start_date' || field === 'planned_finish_date') return dateText(value);
    if (field === 'status') return statusNames[value] || value;
    if (typeof value === 'boolean') return value ? 'Да' : 'Нет';
    if (['early_start','early_finish'].includes(field)) return `День ${value}`;
    if (['duration','start_delay','remaining_duration','slack'].includes(field)) return `${value} дн.`;
    return value || 'Не назначен';
  };
  return items.map(item => {
    const fields = {...item.changes, ...item.schedule_changes};
    if (data.after.calendar?.configured) { delete fields.early_start; delete fields.early_finish; }
    if (fields.duration && !fields.status) delete fields.remaining_duration;
    return `<section class="task-change"><strong>${esc(item.name)}${item.type === 'added' ? ' · новая задача' : ''}</strong><dl>${Object.entries(fields).filter(([key]) => labels[key]).map(([key, change]) => `<div><dt>${labels[key]}</dt><dd><span>${esc(format(key, change.before, true))}</span>${icon('arrowRight')}<strong>${esc(format(key, change.after, false))}</strong></dd></div>`).join('')}</dl></section>`;
  }).join('');
}

export function impactMarkup(data) {
  const diff = data.diff, summary = data.after.summary;
  const dated = data.after.calendar?.configured;
  const consequences = diff.consequences || diff.affected_tasks;
  const moved = consequences.some(task => task.shift_days || task.finish_shift_days);
  const name = id => data.after.tasks.find(task => task.id === id)?.name || id;
  const status = diff.requires_action ? 'Нужно внимание' : diff.existing_issues_remain ? 'Прежние риски сохраняются' : 'Без новых угроз';
  return `${data.ai?.source === 'pending' ? '<p class="field-hint" role="status">Готовлю пояснение…</p>' : aiNotice(data)}
    <span class="status-pill ${diff.requires_action || diff.existing_issues_remain ? 'amber' : 'green'}">${status}</span>
    <div class="result-summary ${dated ? 'calendar-result' : ''}"><span class="before">${dated ? dateText(diff.old_finish_date) : diff.old_duration}</span>${icon('arrowRight')}<span class="after">${dated ? dateText(diff.new_finish_date) : diff.new_duration}</span>${dated ? '' : '<small>раб. дн.</small>'}</div>
    <div class="result-stat-row"><span class="status-pill ${diff.duration_delta > 0 ? 'amber' : 'green'}">${signed(diff.duration_delta)} дн. к прогнозу</span><span class="status-pill ${summary.deadline_breached ? 'red' : 'violet'}">${summary.project_deadline == null ? 'Без дедлайна' : summary.deadline_breached ? `Превышение ${summary.delay_vs_deadline} дн.` : `Дедлайн ${dated ? dateText(summary.deadline_date) : `${summary.project_deadline} дн.`}`}</span></div>
    ${summary.status_conflicts?.length ? '<p class="field-hint">Статусы противоречат зависимостям. Прогноз требует проверки.</p>' : ''}
    <h4 class="result-subtitle">Ваши изменения</h4>${taskChangesMarkup(diff.edited_tasks || [], data) || '<p class="prose">Параметры задач не изменились.</p>'}
    <h4 class="result-subtitle">Влияние на другие задачи</h4>
    ${!moved ? '<p class="prose">Последующие задачи не сдвигаются.</p>' : ''}
    ${taskChangesMarkup(consequences, data)}
    <h4 class="result-subtitle">Под угрозой · ${summary.at_risk.length}</h4><p class="prose">${summary.at_risk.map(id => esc(name(id))).join(', ') || 'Нет задач под угрозой.'}</p>
    <details class="result-details"><summary>Объяснение и критический путь</summary><div class="prose">${richText(data.explanation)}<p><strong>${summary.critical_branching ? 'Критические задачи всех веток' : 'Критический путь'}:</strong> ${(summary.critical_branching ? summary.critical_tasks : summary.critical_path).map(id => esc(name(id))).join(summary.critical_branching ? ', ' : ' → ') || 'не определён'}</p></div></details>`;
}

export function renderSandbox(session) {
  $('#sandboxCard').hidden = !session.active;
  $('#assistantTitle').textContent = session.active ? 'Разбор сценария' : 'Ассистент проекта';
  ['#radarSummary','#messages','.assistant-compose'].forEach(selector => { $(selector).hidden = session.active; });
  if (!session.active) return;
  const {phase, data, aiPhase} = session;
  const pending = ['calculating','dragging'].includes(phase);
  $('#sbApply').disabled = !session.canApply;
  $('#sbApply').textContent = phase === 'applying' ? 'Сохраняю…' : 'Применить сценарий';
  $('#sbReset').disabled = phase === 'applying' || phase === 'conflict' || !session.dirty;
  $('#sbExit').disabled = phase === 'applying';
  $('#sbReload').hidden = phase !== 'conflict';
  $('#sbRetry').hidden = !(phase === 'ready' && ['error','fallback'].includes(aiPhase)) && phase !== 'error';
  $('#sbRetry').textContent = phase === 'error' ? 'Повторить расчёт' : 'Повторить объяснение';
  $('#sandboxInfo').setAttribute('aria-busy', String(pending));
  if (phase === 'idle') {
    $('#sandboxInfo').innerHTML = `<div class="sandbox-empty">${icon('branches')}<h3>Проверьте другой план</h3><p>Перетащите задачу, которая ещё не начата. Можно сдвинуть несколько задач, а затем применить весь сценарий.</p><p>Стрелки ← → сдвигают выбранную полосу на рабочий день.</p></div>`;
    return;
  }
  if (pending) {
    $('#sandboxInfo').innerHTML = `<p class="sandbox-progress" role="status">${icon('activity')}${phase === 'dragging' ? 'Отпустите задачу для расчёта' : 'Пересчитываю сроки и зависимости…'}</p>`;
    return;
  }
  if (['error','conflict'].includes(phase)) {
    $('#sandboxInfo').innerHTML = `<p class="sandbox-error" role="alert">${esc(session.error)}</p>`;
    return;
  }
  if (!data) return;
  const summary = data.after.summary, diff = data.diff;
  const dated = data.after.calendar?.configured;
  const direct = new Set(data.changes.map(change => change.task_id));
  const affected = diff.affected_tasks.filter(task => task.shift_days && !direct.has(task.id));
  const risk = summary.risk_assessment?.level || data.changes[0]?.risk;
  const riskBasis = summary.risk_assessment?.basis || data.changes[0]?.risk_basis || '';
  const deadline = summary.project_deadline;
  const reserve = deadline == null ? null : summary.deadline_reserve ?? deadline - summary.project_duration;
  const timing = reserve == null ? 'Дедлайн не задан' : reserve < 0 ? `Превышение дедлайна: ${-reserve} дн.` : `Запас до дедлайна: ${reserve} дн.`;
  const explanation = ['waiting','loading'].includes(aiPhase)
    ? `<p class="sandbox-progress" role="status">${icon('sparkles')}Готовлю объяснение сценария…</p>`
    : `${['error','fallback'].includes(aiPhase) ? '<p class="field-hint">Пояснение ИИ пока недоступно. Расчёт сценария готов.</p>' : ''}<div class="prose">${richText(data.explanation)}</div>`;
  $('#sandboxInfo').innerHTML = `<div class="sandbox-forecast ${dated ? 'calendar-result' : ''}"><span>Прогноз завершения</span><div><span>${dated ? dateText(diff.old_finish_date) : diff.old_duration}</span>${icon('arrowRight')}<strong>${dated ? dateText(diff.new_finish_date) : diff.new_duration}</strong>${dated ? '' : '<small>раб. дн.</small>'}</div><p>${diff.duration_delta ? `${signed(diff.duration_delta)} дн. к сохранённому плану` : 'Общий срок не меняется'}</p></div><div class="sandbox-deadline ${reserve != null && reserve < 0 ? 'late' : ''}"><strong>${timing}</strong><span title="${esc(riskBasis)}">${deadline == null ? 'Риск нарушения срока не определён' : `Дедлайн ${dated ? dateText(summary.deadline_date) : `${deadline} дн.`} · риск ${risk}`}</span></div><h3 class="sandbox-subtitle">Ваши изменения · ${data.changes.length}</h3><ul class="sandbox-task-list">${data.changes.map(change => `<li><span>${esc(change.task)}</span><strong>${dated ? `${dateText(change.old_start_date)} → ${dateText(change.new_start_date)}` : `День ${change.old_start} → ${change.new_start}`}</strong></li>`).join('')}</ul><h3 class="sandbox-subtitle">Следом сдвинутся · ${affected.length}</h3><ul class="sandbox-task-list">${affected.map(task => `<li><span>${esc(task.name)}</span><strong>${signed(task.shift_days)} дн.</strong></li>`).join('') || '<li>Другие задачи не сдвигаются</li>'}</ul><div class="sandbox-explanation"><h3>${icon('sparkles')}Что это значит</h3>${explanation}</div>`;
}

export function renderRadar(data, state) {
  const risk = state.analysis?.summary.at_risk.length || 0;
  const clean = !data.signals.length;
  $('#radarSummary').className = `radar-summary${clean ? ' clean' : ''}`;
  $('#radarSummary').innerHTML = `<span class="radar-orbit">${icon(clean ? 'checkCircle' : 'radar')}</span><div><strong>${clean ? 'План без явных рисков' : risk ? `${risk} ${plural(risk, 'задача', 'задачи', 'задач')} под угрозой` : 'Есть сигналы риска'}</strong><p>${clean ? 'По данным текущего плана' : 'Радар обновлён по текущему плану'}</p></div>`;
}
