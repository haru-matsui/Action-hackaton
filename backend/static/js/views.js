import {$, escapeHTML as esc, icon, avatar, statusPill, statusNames, richText, emptyState, signed, plural, aiNotice} from './ui.js';

export function renderProject(state) {
  const project = state.project;
  const tasks = state.analysis?.tasks || [];
  const summary = state.analysis?.summary;
  const done = tasks.filter(task => task.status === 'done').length;
  const active = tasks.filter(task => task.status === 'in_progress').length;
  const percent = tasks.length ? Math.round(done / tasks.length * 100) : 0;
  $('#projectTitle').textContent = project?.name || 'Начните с первого проекта';
  $('#projectDescription').textContent = project?.description || (project ? 'Весь план перед глазами. Оценивайте изменения до того, как они станут проблемой.' : 'Создайте проект, добавьте задачи и соберите понятный план действий.');
  document.title = `${project?.name || 'Мои проекты'} · PM Radar`;
  $('#teamAvatars').innerHTML = (state.owners || []).slice(0, 5).map(avatar).join('');
  $('#navTaskCount').textContent = tasks.length;
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
  const critical = summary?.critical_path.length || 0;
  const atRisk = summary?.at_risk.length || 0;
  const reserve = deadline == null ? null : deadline - duration;
  const deadlineNote = reserve == null ? 'Дедлайн не установлен' : reserve < 0 ? `На ${-reserve} дн. позже дедлайна` : `В запасе ${reserve} раб. дн.`;
  $('#badges').innerHTML = `
    <article class="metric ${reserve != null && reserve <= 2 ? 'amber' : ''}"><div class="metric-title">Прогноз завершения${icon('clock')}</div><div class="metric-value"><b>${duration}</b><span>${deadline == null ? 'дней' : `/ ${deadline} дн.`}</span></div><div class="mini-meter"><span style="width:${deadline ? Math.min(100, duration / deadline * 100) : 0}%"></span></div><div class="metric-note">${deadlineNote}</div></article>
    <article class="metric"><div class="metric-title">Выполнено задач${icon('checkCircle')}</div><div class="metric-value"><b>${done}</b><span>/ ${tasks.length}</span></div><div class="mini-meter"><span class="segment-done" style="width:${percent}%"></span><span class="segment-active" style="width:${tasks.length ? active / tasks.length * 100 : 0}%"></span></div><div class="metric-note">${percent}% проекта завершено</div></article>
    <article class="metric violet"><div class="metric-title">Критический путь${icon('route')}</div><div class="metric-value"><b>${critical}</b><span>${plural(critical, 'задача', 'задачи', 'задач')}</span></div><div class="mini-chain" aria-hidden="true">${Array.from({length:Math.min(critical, 8)}, () => '<i></i>').join('')}</div><div class="metric-note">Определяют общий срок</div></article>
    <article class="metric amber"><div class="metric-title">Под угрозой${icon('flag')}</div><div class="metric-value"><b>${atRisk}</b><span>${plural(atRisk, 'задача', 'задачи', 'задач')}</span></div><div class="mini-risks" aria-hidden="true">${tasks.slice(0, 14).map(task => `<i class="${summary?.at_risk.includes(task.id) ? 'risk' : ''}"></i>`).join('')}</div><div class="metric-note">${atRisk ? 'Нуждаются во внимании' : 'Риски не обнаружены'}</div></article>`;
  $('#badges').setAttribute('aria-busy', 'false');
  const alert = $('#projectAlert');
  alert.hidden = !tasks.length;
  alert.className = `attention-banner ${summary?.deadline_breached ? 'danger' : atRisk ? '' : 'good'}`;
  let heading, note;
  if (summary?.deadline_breached) {
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
  const summary = state.analysis?.summary;
  const horizon = Math.max(summary?.project_duration || 0, summary?.project_deadline || 0, 1);
  const maxDay = horizon + Math.max(2, Math.ceil(horizon * .08));
  const step = Math.max(1, Math.ceil(horizon / 6 / 5) * 5);
  return {maxDay, step, percent: day => day / maxDay * 100};
}

export function renderTimeline(state) {
  const tasks = state.analysis?.tasks || [];
  if (!tasks.length) {
    $('#timeline').innerHTML = emptyState('У хорошего плана есть начало', 'Добавьте первую задачу и назначьте ответственного.', `<button class="button primary" data-action="${state.project ? 'add-task' : 'new-project'}">${icon('plus')}${state.project ? 'Добавить задачу' : 'Создать проект'}</button>`);
    return;
  }
  const {maxDay, step, percent} = timelineScale(state);
  const deadline = state.analysis.summary.project_deadline;
  const ticks = [];
  for (let day = 0; day <= maxDay; day += step) {
    if (deadline != null && Math.abs(day - deadline) < step * .6) continue;
    ticks.push(`<span class="gantt-tick" style="left:${percent(day)}%">${day}</span>`);
  }
  const axis = `<div class="gantt-axis"><div class="gantt-axis-label">ЗАДАЧА / ОТВЕТСТВЕННЫЙ</div><div class="gantt-axis-track">${ticks.join('')}${deadline != null ? `<span class="deadline-label" style="left:${percent(deadline)}%">Дедлайн · ${deadline}</span>` : ''}</div></div>`;
  $('#timeline').classList.toggle('sandbox-mode', state.sandbox);
  $('#timeline').innerHTML = axis + tasks.map(task => {
    const width = Math.max(percent(task.early_finish - task.early_start), 1);
    const risk = state.analysis.summary.at_risk.includes(task.id);
    const title = task.status === 'done' ? `${task.name} — выполнена` : `${task.name}: дни ${task.early_start}–${task.early_finish}, резерв ${task.slack} дн.`;
    return `<div class="gantt-row"><div class="gantt-meta"><span class="gantt-status ${task.status}" title="${statusNames[task.status]}">${task.status === 'done' ? icon('check') : ''}</span><div class="gantt-task-info"><button class="task-name" data-task-id="${esc(task.id)}" title="${esc(task.name)}">${esc(task.name)}</button><span class="gantt-owner">${esc(task.owner || 'Не назначен')}</span></div></div><div class="gantt-track" style="--tick-width:${percent(step)}%">${deadline != null ? `<div class="gantt-deadline" style="left:${percent(deadline)}%"></div>` : ''}<button class="gantt-bar ${task.status} ${task.is_critical ? 'critical' : ''} ${risk ? 'at-risk' : ''}" data-task-id="${esc(task.id)}" data-duration="${task.duration}" data-original-width="${width}" data-original-left="${percent(task.early_start)}" data-start-delay="${task.start_delay || 0}" style="left:${percent(task.early_start)}%;width:${width}%" title="${esc(title)}" aria-label="${esc(title)}">${task.status === 'done' ? icon('check') : `<span class="bar-label">${task.early_finish - task.early_start}</span><span class="bar-grip"></span>`}</button></div></div>`;
  }).join('');
}

function renderTable(state) {
  const tasks = state.analysis?.tasks || [];
  $('#taskTable').innerHTML = `<thead><tr><th scope="col">Задача</th><th scope="col">Ответственный</th><th scope="col">Статус</th><th scope="col">Длительность</th><th scope="col">Резерв</th><th scope="col">Зависит от</th><th scope="col"><span class="sr-only">Действия</span></th></tr></thead><tbody>${tasks.map((task, index) => `<tr><td><div class="table-task"><span class="task-number">${String(index + 1).padStart(2, '0')}</span><div><button class="task-name" data-task-id="${esc(task.id)}">${esc(task.name)}</button><span class="table-period">${task.status === 'done' ? 'Завершена' : `День ${task.early_start} → ${task.early_finish}`}</span></div></div></td><td><div class="owner-cell">${avatar(task.owner || 'Не назначен')}<span>${esc(task.owner || 'Не назначен')}</span></div></td><td>${statusPill(task.status)}</td><td>${task.duration} дн.</td><td class="${task.at_risk ? 'slack-critical' : ''}">${task.slack} дн.</td><td class="dependency-names">${task.dependencies.map(id => esc(tasks.find(item => item.id === id)?.name || id)).join(', ') || '—'}</td><td><button class="icon-button" data-explain="${esc(task.id)}" title="Объяснить задачу" aria-label="Объяснить задачу ${esc(task.name)}">${icon('sparkles')}</button></td></tr>`).join('') || '<tr><td colspan="7">Добавьте задачи, чтобы увидеть расчётный план.</td></tr>'}</tbody>`;
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
  const critical = state.analysis.summary.critical_path;
  const criticalEdges = new Set(critical.slice(1).map((id, index) => `${critical[index]}→${id}`));
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
    return `<g class="graph-node ${task.is_critical ? 'critical' : ''} ${task.status}" transform="translate(${pos.x},${pos.y})" data-task-id="${esc(task.id)}" role="button" tabindex="0" aria-label="${esc(task.name)}"><title>${esc(task.name)} · ${esc(task.owner || 'Не назначен')}</title><rect width="${nodeWidth}" height="${nodeHeight}" rx="10"/><circle class="graph-status" cx="${nodeWidth-13}" cy="17" r="3"/>${lines.map((line, i) => `<text class="node-title" x="13" y="${lines.length === 1 ? 28 : 22 + i*15}">${esc(line)}</text>`).join('')}<text class="node-meta" x="13" y="59">${task.status === 'done' ? 'Выполнено' : `${task.duration} дн. · резерв ${task.slack} дн.`}</text></g>`;
  }).join('');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('width', width);
  svg.setAttribute('height', height);
  svg.innerHTML = `<defs><marker id="normalArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#d9dce8"/></marker><marker id="criticalArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#baa9df"/></marker></defs>${edges}${nodes}`;
}

function renderPath(state) {
  const tasks = state.analysis?.tasks || [];
  const path = state.analysis?.summary.critical_path || [];
  $('#pathDuration').textContent = tasks.length ? `${state.analysis.summary.project_duration} рабочих дней` : '';
  $('#criticalPath').innerHTML = path.map(id => {
    const task = tasks.find(item => item.id === id);
    return `<button class="path-node ${task.status === 'done' ? 'done' : ''}" data-task-id="${esc(id)}">${task.status === 'done' ? icon('check') : ''}${esc(task.name)}</button>`;
  }).join(icon('arrowRight', 'path-arrow')) || '<span class="field-hint">Путь появится, когда в проекте будут задачи.</span>';
}

export function impactMarkup(data) {
  const diff = data.diff, summary = data.after.summary;
  const affected = diff.affected_tasks.filter(task => task.shift_days && (!diff.downstream || diff.downstream.includes(task.id)));
  const name = id => data.after.tasks.find(task => task.id === id)?.name || id;
  return `${aiNotice(data)}<span class="status-pill ${diff.requires_action ? 'amber' : 'green'}">${diff.requires_action ? 'Нужно внимание' : 'Без новых угроз'}</span><div class="result-summary"><span class="before">${diff.old_duration}</span>${icon('arrowRight')}<span class="after">${diff.new_duration}</span><small>раб. дн.</small></div><div class="result-stat-row"><span class="status-pill ${diff.duration_delta > 0 ? 'amber' : 'green'}">${signed(diff.duration_delta)} дн. к сроку</span><span class="status-pill ${summary.deadline_breached ? 'red' : 'violet'}">${summary.project_deadline == null ? 'Без дедлайна' : summary.deadline_breached ? `Просрочка ${summary.delay_vs_deadline} дн.` : `Дедлайн ${summary.project_deadline} дн.`}</span></div><h4 class="result-subtitle">Затронутые последующие задачи</h4><ul class="affected-list">${affected.map(task => `<li><span>${esc(task.name)}</span><strong>${signed(task.shift_days)} дн.</strong></li>`).join('') || '<li>Последующие задачи не сдвигаются</li>'}</ul><h4 class="result-subtitle">Под угрозой · ${summary.at_risk.length}</h4><p class="prose">${summary.at_risk.map(id => esc(name(id))).join(', ') || 'Нет задач под угрозой.'}</p><details class="result-details"><summary>Объяснение и критический путь</summary><div class="prose">${richText(data.explanation)}<p><strong>Критический путь:</strong> ${summary.critical_path.map(id => esc(name(id))).join(' → ') || 'не определён'}</p></div></details>`;
}

export function renderSandbox(data) {
  const fact = data.fact;
  $('#sandboxInfo').innerHTML = `<p class="prose"><strong>${esc(fact.task)}</strong> · сдвиг начала ${signed(fact.shift)} дн.</p><div class="result-stat-row"><span class="status-pill violet">К сроку проекта: ${signed(fact.duration_delta)} дн.</span><span class="status-pill ${fact.risk === 'высокий' ? 'red' : 'amber'}">Риск: ${esc(fact.risk)}</span></div><div class="prose">${aiNotice(data)}${richText(data.explanation)}</div>`;
  $('#sandboxCard').hidden = false;
}

export function renderRadar(data, state) {
  const risk = state.analysis?.summary.at_risk.length || 0;
  const clean = !data.signals.length;
  $('#radarSummary').className = `radar-summary${clean ? ' clean' : ''}`;
  $('#radarSummary').innerHTML = `<span class="radar-orbit">${icon(clean ? 'checkCircle' : 'radar')}</span><div><strong>${clean ? 'План без явных рисков' : risk ? `${risk} ${plural(risk, 'задача', 'задачи', 'задач')} под угрозой` : 'Есть сигналы риска'}</strong><p>${clean ? 'Сроки и загрузка проверены' : 'Радар обновлён по текущему плану'}</p></div>`;
}
