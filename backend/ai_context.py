"""Authoritative JSON for the language model: all arithmetic runs in Python."""
from ai_features import workload_by_owner, radar
from schedule import downstream_of

def project_facts(project: dict, analysis: dict, mode: str, **extra) -> dict:
    tasks = analysis['tasks']
    done = [t for t in tasks if t['status'] == 'done']
    work = sum(t['duration'] for t in tasks)
    completed_work = sum(t['duration'] for t in done)
    signals = radar(analysis)
    return {
        'mode': mode, 'project': {'name': project['name'], 'description': project.get('description', '')},
        'summary': analysis['summary'], 'tasks': tasks,
        'statistics': {'total_tasks': len(tasks), 'done_count': len(done),
            'unfinished_count': len(tasks) - len(done),
            'in_progress_count': sum(t['status'] == 'in_progress' for t in tasks),
            'completion_percent_by_task_count': round(100 * len(done) / len(tasks)) if tasks else 0,
            'completion_percent_by_planned_work': round(100 * completed_work / work) if work else 0,
            'done_names': [t['name'] for t in done],
            'unfinished_names': [t['name'] for t in tasks if t['status'] != 'done'],
            'requires_attention': bool(signals),
            'status': 'под угрозой' if analysis['summary']['deadline_breached'] else 'требует внимания' if signals else 'в норме'},
        'workload': workload_by_owner(analysis), 'risk_signals': signals,
        'action_options': [s['suggestion'] for s in signals[:3]],
        'limitations': ['Нет календарных дат, текущего календарного дня и фактических причин задержек.',
            'Загрузка — количество незавершённых задач всего проекта, не за неделю.',
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
