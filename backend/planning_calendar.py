"""Calendar projection of remaining work. Weekdays only; deadlines are inclusive."""
from datetime import date, datetime, timedelta
import os
import re
from zoneinfo import ZoneInfo

from schedule import analyze, deadline_risk

TIMEZONE = os.environ.get('PM_RADAR_TIMEZONE', 'Asia/Yekaterinburg')


def today():
    return datetime.now(ZoneInfo(TIMEZONE)).date()


def parse_date(value, label='Дата'):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError(f'{label}: укажите дату в формате ГГГГ-ММ-ДД.')
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f'{label}: такой даты не существует.') from None
    if not 2000 <= parsed.year <= 2100:
        raise ValueError(f'{label}: допустимы даты с 2000 по 2100 год.')
    return parsed


def next_workday(day):
    return day + timedelta(days=7-day.weekday()) if day.weekday() >= 5 else day


def add_workdays(day, count):
    """Index weekdays from an inclusive working-day origin; supports negative offsets."""
    day = next_workday(day)
    weeks, rest = divmod(count, 5)
    try:
        result = day + timedelta(days=weeks * 7 + rest)
        if day.weekday() + rest >= 5:
            result += timedelta(days=2)
    except OverflowError:
        raise ValueError('Оценки задач слишком велики для календарного прогноза. Уменьшите сроки.') from None
    return result


def working_days_between(start, end):
    """Signed count of weekdays in [start, end)."""
    if end < start:
        return -working_days_between(end, start)
    weeks, rest = divmod((end-start).days, 7)
    return weeks * 5 + sum((start.weekday()+i) % 7 < 5 for i in range(rest))


def date_label(value):
    if not value:
        return 'не задана'
    parsed = date.fromisoformat(value) if isinstance(value, str) else value
    return parsed.strftime('%d.%m.%Y')


def set_dates(project, body):
    if not {'start_date', 'deadline_date'}.intersection(body):
        return
    if 'deadline' in body:
        raise ValueError('Укажите календарный дедлайн без числового срока.')
    start = parse_date(body.get('start_date', project.get('start_date')), 'Начало проекта')
    if start < today() and start.isoformat() != project.get('start_date'):
        raise ValueError('Дата начала не может быть раньше сегодняшней.')
    raw_deadline = body.get('deadline_date', project.get('deadline_date'))
    deadline = None if raw_deadline in (None, '') else parse_date(raw_deadline, 'Дедлайн')
    if deadline and deadline < start:
        raise ValueError('Дедлайн не может быть раньше начала проекта.')
    project.update(start_date=start.isoformat(), deadline_date=deadline.isoformat() if deadline else None,
                   deadline=None)


def calendar_info(as_of=None):
    current = as_of or today()
    return {'today': current.isoformat(), 'timezone': TIMEZONE,
            'next_workday': next_workday(current).isoformat(), 'working_week': 'Пн–Пт'}


def analyze_project(project, tasks=None, as_of=None):
    tasks = project['tasks'] if tasks is None else tasks
    current = as_of or today()
    if isinstance(current, str):
        current = date.fromisoformat(current)
    clock = calendar_info(current)
    if not project.get('start_date'):
        result = analyze(tasks, project.get('deadline'))
        old_deadline = project.get('deadline')
        result['calendar'] = {**clock, 'configured': False,
            'suggested_deadline_date': add_workdays(current, old_deadline-1).isoformat() if old_deadline else None}
        return result
    start = parse_date(project['start_date'], 'Начало проекта')
    deadline = parse_date(project['deadline_date'], 'Дедлайн') if project.get('deadline_date') else None
    # The user-selected start anchors the plan, including dates in the past.
    # Today is a marker, never an implicit rewrite of the saved schedule.
    origin = next_workday(start)
    capacity = working_days_between(origin, deadline + timedelta(days=1)) if deadline else None
    unfinished = any(t.get('status') != 'done' for t in tasks)
    result = analyze(tasks, capacity if unfinished else None)
    summary = result['summary']
    summary['project_deadline'] = capacity
    summary['time_basis'] = 'remaining_work_from_project_start'
    finish = add_workdays(origin, max(0, summary['project_duration']-1)) if unfinished else None
    summary.update(forecast_finish_date=finish.isoformat() if finish else None,
                   deadline_date=deadline.isoformat() if deadline else None,
                   planning_date=origin.isoformat())
    # A zero-day milestone still has a calendar date. It cannot meet yesterday's deadline.
    forecast_days = max(1, summary['project_duration']) if unfinished else 0
    reserve = capacity - forecast_days if capacity is not None and unfinished else None
    summary['deadline_reserve'] = reserve
    summary['deadline_breached'] = reserve is not None and reserve < 0
    summary['delay_vs_deadline'] = max(0, -reserve) if reserve is not None else 0
    summary['risk_assessment'] = deadline_risk(forecast_days, capacity)
    if not unfinished:
        summary['risk_assessment'] = {'level':'не определён', 'basis':'Нет незавершённых задач.', 'probability':None}
    axis_start = next_workday(min(start, current))
    offset = working_days_between(axis_start, origin)
    today_offset = max(0, working_days_between(axis_start, current))
    # The axis labels the start of each workday. An inclusive deadline affects
    # capacity through that day, but its visual marker belongs on the date itself.
    # A weekend has no column, so its marker sits at the next workday boundary.
    deadline_offset = working_days_between(axis_start, deadline) if deadline else None
    horizon = max(offset + summary['project_duration'], deadline_offset or 0, today_offset+1, 1)
    padding = max(2, (horizon+12)//13)
    max_day = horizon + padding
    step = max(1, ((horizon+29)//30)*5)
    ticks = [{'offset': i, 'date': add_workdays(axis_start, i).isoformat()} for i in range(0,max_day+1,step)]
    completed_days = max(0, working_days_between(start,current))
    current_day = completed_days+1 if current >= start and current.weekday() < 5 else None
    calendar = {**clock, 'configured': True, 'start_date':start.isoformat(),
        'deadline_date':summary['deadline_date'], 'planning_date':origin.isoformat(),
        'project_started':current >= start, 'is_workday':current.weekday() < 5,
        'current_workday':current_day, 'completed_workdays':completed_days,
        'axis_start':axis_start.isoformat(), 'planning_offset':offset,
        'today_offset':today_offset, 'deadline_offset':deadline_offset,
        'max_day':max_day, 'step':step, 'ticks':ticks}
    result['calendar'] = calendar
    for task in result['tasks']:
        done = task['status'] == 'done'
        end = max(0, task['early_finish']-1)
        beginning = min(task['early_start'], end)
        task['planned_start_date'] = None if done else add_workdays(origin,beginning).isoformat()
        task['planned_finish_date'] = None if done else add_workdays(origin,end).isoformat()
        task['calendar_start_offset'] = None if done else offset + task['early_start']
        task['calendar_finish_offset'] = None if done else offset + task['early_finish']
    return result
