"""Authoritative JSON for the language model: all arithmetic runs in Python."""
from ai_features import workload_by_owner, radar
from schedule import downstream_of, progress_summary

def project_facts(project: dict, analysis: dict, mode: str, **extra) -> dict:
    tasks = analysis['tasks']
    done = [t for t in tasks if t['status'] == 'done']
    signals = radar(analysis)
    return {
        'mode': mode, 'project': {'name': project['name'], 'description': project.get('description', '')},
        'summary': analysis['summary'], 'tasks': tasks, 'calendar': analysis.get('calendar'),
        'time_model': {
            'unit': 'рабочие дни, понедельник–пятница; праздники не учитываются',
            'origin': analysis.get('calendar', {}).get('planning_date', 'текущая точка планирования, день 0'),
            'deadline': ('фиксированная календарная дата, включительно' if analysis.get('calendar', {}).get('configured')
                         else 'номер рабочего дня от той же точки планирования'),
            'duration': 'оставшаяся оценка для незавершённых задач; сохранённая оценка для выполненных',
            'remaining_duration': 'ноль для выполненных задач',
            'actual_dates_known': False,
            'forecast_conditional': bool(analysis['summary'].get('status_conflicts')),
        },
        'statistics': {**analysis['summary'].get('progress', progress_summary(tasks)),
            'progress_basis': 'доля завершённых задач; не объём работы и не трудозатраты',
            'done_names': [t['name'] for t in done],
            'unfinished_names': [t['name'] for t in tasks if t['status'] != 'done'],
            'requires_attention': bool(signals),
            'status': 'под угрозой' if analysis['summary']['deadline_breached'] else 'требует внимания' if signals else 'в норме'},
        'workload': workload_by_owner(analysis), 'risk_signals': signals,
        'workload_basis': 'количество незавершённых задач всего проекта; не одновременная занятость',
        'risk_basis': 'уровень по запасу до дедлайна, не статистическая вероятность срыва',
        'action_options': [s['suggestion'] for s in signals[:3]],
        'limitations': ['Фактические даты выполнения задач и причины задержек неизвестны.',
            *([] if analysis.get('calendar', {}).get('configured') else ['Дата начала проекта не задана; календарный прогноз неизвестен.']),
            'Количество задач не доказывает перегрузку и не показывает рабочие часы или занятость по дням.',
            'Навыки, доступность, отпуск и больничные сотрудников неизвестны.',
            'Любое изменение требует явного подтверждения пользователя.'],
        **extra,
    }

def task_facts(analysis: dict, task_id: str) -> dict:
    by_id = {t['id']: t for t in analysis['tasks']}
    task = by_id[task_id]
    return {'selected_task': task,
        'waiting_on': [by_id[d] for d in task['dependencies'] if by_id[d]['status'] != 'done'],
        'downstream_tasks': [by_id[d] for d in downstream_of(analysis['tasks'], task_id)],
        'cause_note': 'Связи показывают очередность работ. Причина незавершённости предшественника неизвестна.'}
