"""Pure sandbox calculations. A scenario is a set of delays against one revision."""
import hashlib
import json

from ai_features import sandbox_json
from schedule import diff_analysis, simulate
from planning_calendar import analyze_project, today, date_label


def revision(project):
    if isinstance(project, dict) and project.get('start_date'):
        project = {'project': project, 'as_of': today().isoformat()}
    return hashlib.sha256(json.dumps(project, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def calculate(project, shifts):
    if not isinstance(shifts, dict):
        raise ValueError('Сдвиги задач должны быть переданы списком изменений.')
    by_id = {task['id']: task for task in project['tasks']}
    cleaned = {}
    for task_id, shift in shifts.items():
        if task_id not in by_id:
            raise ValueError('Одна из задач сценария больше не существует.')
        if type(shift) is not int:
            raise ValueError('Сдвиг задаётся целым числом рабочих дней.')
        if not shift:
            continue
        task = by_id[task_id]
        if task['status'] != 'todo':
            raise ValueError('Сдвигать начало можно только у задач, которые ещё не начаты.')
        delay = int(task.get('start_delay', 0)) + shift
        if delay < 0:
            raise ValueError('Задача не может стартовать раньше завершения предшественников.')
        if delay > 100000:
            raise ValueError('Сдвиг слишком большой: допустимо до 100000 рабочих дней ожидания.')
        cleaned[task_id] = shift
    before = analyze_project(project)
    tasks = simulate(project['tasks'], {key: {'start_delay': value} for key, value in cleaned.items()})
    after = analyze_project(project, tasks, before['calendar']['today'])
    previous = {task['id']: task for task in before['tasks']}
    for task in after['tasks']:
        if task['status'] != 'todo' and task['early_start'] != previous[task['id']]['early_start']:
            raise ValueError(f"Сценарий сдвигает уже начатую или выполненную задачу «{task['name']}». Проверьте её зависимости.")
    diff = diff_analysis(before, after)
    changes = [sandbox_json(before, after, diff, key, value) for key, value in cleaned.items()]
    base_revision = revision(project)
    key = revision({'base_revision': base_revision, 'shifts': cleaned})
    return {'before': before, 'after': after, 'diff': diff, 'changes': changes,
            'shifts': cleaned, 'base_revision': base_revision, 'scenario_key': key,
            'after_summary': after['summary'], 'saved': False}


def describe(result):
    changes, diff, summary = result['changes'], result['diff'], result['after_summary']
    if not changes:
        return 'Изменений нет. Показан сохранённый план.'
    lines = ['Сценарий не сохранён.']
    for change in changes:
        if change.get('new_start_date'):
            lines.append(f"«{change['task']}»: начало — {date_label(change['old_start_date'])} → {date_label(change['new_start_date'])}.")
        else:
            lines.append(f"«{change['task']}»: начало — день {change['old_start']} → {change['new_start']}.")
    delta = diff['duration_delta']
    if result['after'].get('calendar', {}).get('configured'):
        lines.append(f"Прогноз завершения: {date_label(diff['old_finish_date'])} → {date_label(diff['new_finish_date'])}.")
        if summary.get('deadline_date'):
            lines.append(f"Дедлайн остаётся {date_label(summary['deadline_date'])}.")
    else:
        lines.append(f"Прогноз завершения: {diff['old_duration']} → {diff['new_duration']} рабочих дней."
                 if delta else f"Прогноз завершения не изменится: {diff['new_duration']} рабочих дней.")
    if summary['project_deadline'] is None:
        lines.append('Дедлайн не задан, поэтому риск его нарушения не определён.')
    elif summary['deadline_breached']:
        lines.append(f"В этом сценарии прогноз превысит дедлайн на {summary['delay_vs_deadline']} дн.")
    else:
        reserve = summary.get('deadline_reserve', summary['project_deadline'] - summary['project_duration'])
        lines.append(f"До дедлайна останется {reserve} дн. запаса.")
    return '\n'.join(lines)
