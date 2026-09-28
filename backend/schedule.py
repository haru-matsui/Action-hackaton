"""Ядро планирования: расчёт раннего/позднего старта, критического пути,
анализ последствий изменений и what-if симуляции.

Модель: проект = набор задач (id, name, duration в днях, dependencies).
Рабочие дни отсчитываются от текущей точки планирования, а не от
исторического начала проекта. duration незавершённой задачи — оставшаяся
оценка, выполненной — сохранённая оценка, не добавляющая оставшейся работы.
Прогноз следует заданным связям; противоречия статусов отмечаются отдельно.
"""
from __future__ import annotations

from typing import Optional
from validation import object_value, integer, boolean


def _topo_order(tasks: list[dict]) -> Optional[list[str]]:
    """Топологическая сортировка. None, если обнаружен цикл."""
    by_id = {t["id"]: t for t in tasks}
    indeg = {t["id"]: len([d for d in t.get("dependencies", []) if d in by_id]) for t in tasks}
    dependents: dict[str, list[str]] = {t["id"]: [] for t in tasks}
    for t in tasks:
        for d in t.get("dependencies", []):
            if d in dependents:
                dependents[d].append(t["id"])
    queue = [tid for tid, deg in indeg.items() if deg == 0]
    order: list[str] = []
    while queue:
        queue.sort()
        cur = queue.pop(0)
        order.append(cur)
        for nxt in dependents[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    return order if len(order) == len(tasks) else None


def analyze(tasks: list[dict], project_deadline: Optional[int] = None) -> dict:
    """Полный CPM-анализ списка задач.

    Возвращает для каждой задачи: early_start/finish, late_start/finish,
    slack (резерв времени), is_critical; плюс сводку по проекту.
    """
    if not tasks:
        return {"tasks": [], "summary": _empty_summary(project_deadline)}

    order = _topo_order(tasks)
    if order is None:
        raise ValueError("В зависимостях между задачами обнаружен цикл")

    by_id = {t["id"]: t for t in tasks}

    # Прямой проход: ранние старт/финиш.
    # Для выполненных задач оставшаяся работа равна нулю. Расчётные позиции
    # графа не являются фактическими датами их начала или завершения.
    es: dict[str, int] = {}
    ef: dict[str, int] = {}
    for tid in order:
        t = by_id[tid]
        preds = [d for d in t.get("dependencies", []) if d in by_id]
        start = max((ef[d] for d in preds), default=0)
        if t.get('status') != 'done':
            start += max(0, int(t.get('start_delay', 0)))
        dur = 0 if t.get("status") == "done" else int(t.get("duration", 0))
        es[tid] = start
        ef[tid] = start + dur

    project_finish = max(ef.values())
    critical_ids = set()

    # Обратный проход: поздние старт/финиш относительно фактического финиша
    # (или дедлайна проекта, если он задан и больше финиша).
    horizon = project_finish
    if project_deadline is not None and project_deadline > horizon:
        horizon = project_deadline
    ls: dict[str, int] = {}
    lf: dict[str, int] = {}
    for tid in reversed(order):
        succs = [s for s in order if tid in by_id[s].get("dependencies", [])]
        finish = min((ls[s] - (max(0, int(by_id[s].get('start_delay', 0)))
                     if by_id[s].get('status') != 'done' else 0) for s in succs), default=horizon)
        dur = 0 if by_id[tid].get("status") == "done" else int(by_id[tid].get("duration", 0))
        lf[tid] = finish
        ls[tid] = finish - dur

    slack = {tid: ls[tid] - es[tid] for tid in by_id}
    # Remove the common deadline reserve to identify every longest branch.
    # Keep a representative path separately; never turn parallel nodes into a chain.
    project_reserve = horizon - project_finish
    critical_ids = {tid for tid in order if slack[tid] == project_reserve and by_id[tid].get('status') != 'done'}
    critical_edges = [[parent, tid] for tid in order if tid in critical_ids
                      for parent in by_id[tid].get('dependencies', [])
                      if parent in critical_ids and ef[parent] +
                      (max(0, int(by_id[tid].get('start_delay', 0)))
                       if by_id[tid].get('status') != 'done' else 0) == es[tid]]
    best_pred: dict[str, str | None] = {}
    for tid in order:
        preds = [parent for parent, child in critical_edges if child == tid]
        best_pred[tid] = max(preds, key=lambda p: ef[p]) if preds else None
    # Later topological nodes win ties, including zero-duration terminal tasks.
    final = max((tid for tid in reversed(order) if tid in critical_ids), key=lambda tid: ef[tid], default=None)
    representative_path = _order_path(final, best_pred) if final is not None else []

    result_tasks = []
    for t in tasks:
        tid = t["id"]
        item = dict(t)
        on_path = tid in critical_ids
        # Задача «под угрозой», если она на критическом пути и её задержка
        # затронет срок проекта: нулевой резерв ИЛИ проект уже впритык к дедлайну.
        tight_vs_deadline = (
            project_deadline is not None and project_finish >= project_deadline - 2
        )
        at_risk = bool(
            on_path
            and t.get("status") != "done"
            and (slack[tid] <= 0 or tight_vs_deadline)
        )
        item.update(
            {
                "early_start": es[tid],
                "remaining_duration": 0 if t.get('status') == 'done' else int(t['duration']),
                "early_finish": ef[tid],
                "late_start": ls[tid],
                "late_finish": lf[tid],
                "slack": slack[tid],
                "is_critical": on_path,
                "at_risk": at_risk,
            }
        )
        result_tasks.append(item)

    deadline_breached = (
        project_deadline is not None and project_finish > project_deadline
    )
    summary = {
        "project_duration": project_finish,
        "project_deadline": project_deadline,
        "deadline_breached": deadline_breached,
        "delay_vs_deadline": (
            max(0, project_finish - project_deadline)
            if project_deadline is not None
            else 0
        ),
        "critical_path": representative_path,
        "critical_tasks": [tid for tid in order if tid in critical_ids],
        "critical_edges": critical_edges,
        "critical_branching": bool(critical_ids) and (set(representative_path) != critical_ids or
                               len(critical_edges) > len(representative_path) - 1),
        "at_risk": sorted([i["id"] for i in result_tasks if i["at_risk"]],
                          key=lambda x: es[x]),
        "has_cycle": False,
        "status_conflicts": status_conflicts(tasks),
        "time_basis": "working_days_from_planning_point",
        "progress": progress_summary(tasks),
        "risk_assessment": deadline_risk(project_finish, project_deadline),
    }
    return {"tasks": result_tasks, "summary": summary}


def _order_path(tail: str, best_pred: dict) -> list[str]:
    """Разворачиваем критический путь как цепочку от финишной задачи назад."""
    path = [tail]
    # разворот по цепочке «предок на пути»
    cur = best_pred.get(tail)
    while cur is not None:
        path.append(cur)
        cur = best_pred.get(cur)
    return list(reversed(path))


def _empty_summary(deadline):
    return {
        "project_duration": 0,
        "project_deadline": deadline,
        "deadline_breached": False,
        "delay_vs_deadline": 0,
        "critical_path": [],
        "critical_tasks": [],
        "critical_edges": [],
        "critical_branching": False,
        "at_risk": [],
        "has_cycle": False,
        "status_conflicts": [],
        "time_basis": "working_days_from_planning_point",
        "progress": progress_summary([]),
        "risk_assessment": deadline_risk(0, deadline),
    }


def progress_summary(tasks):
    total = len(tasks)
    done = sum(t.get('status') == 'done' for t in tasks)
    return {'total_tasks': total, 'done_count': done, 'unfinished_count': total - done,
            'in_progress_count': sum(t.get('status') == 'in_progress' for t in tasks),
            'completion_percent_by_task_count': (200 * done + total) // (2 * total) if total else 0}


def deadline_risk(finish, deadline):
    """A transparent product rule based on reserve, never a probability."""
    if deadline is None:
        return {'level': 'не определён', 'basis': 'Дедлайн не задан.', 'probability': None}
    reserve = deadline - finish
    if reserve < 0:
        level, basis = 'высокий', f'Прогноз превышает дедлайн на {-reserve} раб. дн.'
    elif reserve == 0:
        level, basis = 'средний', 'Прогноз совпадает с дедлайном, запаса нет.'
    elif reserve <= 2:
        level, basis = 'умеренный', f'До дедлайна осталось {reserve} раб. дн. запаса.'
    else:
        level, basis = 'низкий', f'До дедлайна осталось {reserve} раб. дн. запаса.'
    return {'level': level, 'basis': basis, 'probability': None}


def status_conflicts(tasks):
    """Do not infer actual dates or silently repair contradictory user statuses."""
    by_id = {t['id']: t for t in tasks}
    return [{'task_id': t['id'], 'status': t['status'], 'unfinished_dependencies': waiting}
            for t in tasks if t.get('status') in {'in_progress', 'done'}
            if (waiting := [d for d in t.get('dependencies', [])
                            if d in by_id and by_id[d].get('status') != 'done'])]


def downstream_of(tasks: list[dict], task_id: str) -> list[str]:
    """Все задачи, транзитивно зависящие от task_id."""
    by_id = {t["id"]: t for t in tasks}
    children: dict[str, list[str]] = {t["id"]: [] for t in tasks}
    for t in tasks:
        for d in t.get("dependencies", []):
            if d in children:
                children[d].append(t["id"])
    seen: list[str] = []
    stack = children.get(task_id, [])[:]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.append(cur)
        stack.extend(children[cur])
    return [s for s in seen if s in by_id]


def diff_analysis(before: dict, after: dict) -> dict:
    """Separate user edits from the recalculated consequences for other tasks."""
    b_tasks = {t["id"]: t for t in before["tasks"]}
    a_tasks = {t["id"]: t for t in after["tasks"]}
    changed, edited, consequences = [], [], []
    input_fields = ('name', 'duration', 'start_delay', 'status', 'owner', 'dependencies')
    calculated_fields = ('early_start', 'early_finish', 'remaining_duration', 'slack', 'is_critical', 'at_risk',
                         'planned_start_date', 'planned_finish_date')

    def value(task, field):
        if field == 'dependencies':
            return sorted(task.get(field, []))
        if field == 'start_delay':
            return task.get(field, 0)
        if field == 'remaining_duration':
            return task.get(field, 0 if task['status'] == 'done' else task['duration'])
        return task.get(field)

    for tid, at in a_tasks.items():
        bt = b_tasks.get(tid)
        direct = {field: {'before': value(bt, field) if bt else None, 'after': value(at, field)}
                  for field in input_fields if bt is None or value(bt, field) != value(at, field)}
        calculated = {field: {'before': value(bt, field) if bt else None, 'after': value(at, field)}
                      for field in calculated_fields if bt is None or value(bt, field) != value(at, field)}
        if not direct and not calculated:
            continue
        item = {'id': tid, 'name': at['name'], 'type': 'added' if bt is None else 'updated',
                'changes': direct, 'schedule_changes': calculated}
        if bt:
            for field, label in [('early_start','shift_days'), ('early_finish','finish_shift_days'), ('slack','slack_delta')]:
                if field in calculated:
                    item[label] = value(at, field) - value(bt, field)
            if 'is_critical' in calculated:
                item['criticality'] = 'now_critical' if at['is_critical'] else 'no_longer_critical'
            if 'at_risk' in calculated:
                item['risk'] = 'now_at_risk' if at['at_risk'] else 'no_longer_at_risk'
        changed.append(item)
        (edited if direct else consequences).append(item)
    for tid, bt in b_tasks.items():
        if tid not in a_tasks:
            item = {'id': tid, 'name': bt['name'], 'type': 'removed', 'changes': {}, 'schedule_changes': {}}
            changed.append(item)
            edited.append(item)

    bs, summary = before['summary'], after['summary']
    duration_delta = summary['project_duration'] - bs['project_duration']
    deadline_now_breached = summary['deadline_breached'] and not bs['deadline_breached']
    new_at_risk = [t for t in summary['at_risk'] if t not in bs['at_risk']]
    old_conflicts = bs.get('status_conflicts', [])
    conflicts = summary.get('status_conflicts', [])
    new_conflicts = [c for c in conflicts if c not in old_conflicts]
    requires_action = bool(duration_delta > 0 or deadline_now_breached or new_at_risk or new_conflicts
                           or any(a.get('shift_days', 0) > 0 for a in changed))
    return {
        'affected_tasks': changed,
        'edited_tasks': edited,
        'consequences': consequences,
        'duration_delta': duration_delta,
        'new_duration': summary['project_duration'],
        'old_duration': bs['project_duration'],
        'old_finish_date': bs.get('forecast_finish_date'),
        'new_finish_date': summary.get('forecast_finish_date'),
        'deadline_breached': summary['deadline_breached'],
        'deadline_newly_breached': deadline_now_breached,
        'new_at_risk': new_at_risk,
        'resolved_risks': [t for t in bs['at_risk'] if t not in summary['at_risk']],
        'new_status_conflicts': new_conflicts,
        'has_current_issues': bool(summary['deadline_breached'] or summary['at_risk'] or conflicts),
        'existing_issues_remain': bool((summary['deadline_breached'] and bs['deadline_breached'])
            or set(summary['at_risk']).intersection(bs['at_risk'])
            or any(c in old_conflicts for c in conflicts)),
        'requires_action': requires_action,
    }


def simulate(tasks: list[dict], changes: dict) -> list[dict]:
    """Что-if симуляция: применяет изменения к копии задач.

    changes: {task_id: {"duration": +N}} — дельта длительности,
             или {"set_done": true}.
    """
    object_value(changes, 'Изменения сценария')
    sim = [dict(t) for t in tasks]
    by_id = {t["id"]: t for t in sim}
    for tid, ch in changes.items():
        t = by_id.get(tid)
        if not t:
            raise ValueError('Задача сценария не найдена.')
        object_value(ch, 'Изменение задачи', {'duration', 'start_delay', 'set_done'})
        for field in ('duration', 'start_delay'):
            if field in ch:
                integer(ch[field], 'Изменение срока', -100000)
        if 'set_done' in ch:
            boolean(ch['set_done'], 'Завершение задачи')
        if "duration" in ch:
            t['duration'] = integer(t.get('duration', 0) + ch['duration'], 'Итоговая длительность')
        if 'start_delay' in ch:
            t['start_delay'] = integer(t.get('start_delay', 0) + ch['start_delay'], 'Итоговое ожидание')
        if ch.get("set_done"):
            t["status"] = "done"
    return sim
