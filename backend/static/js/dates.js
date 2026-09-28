// Presentation only. All scheduling dates and working-day offsets come from the server.
const months = ['янв.','февр.','мар.','апр.','мая','июн.','июл.','авг.','сент.','окт.','нояб.','дек.'];

export function dateText(value, short = false) {
  if (!value) return '—';
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return '—';
  const [,year,month,day] = match;
  return short ? `${Number(day)} ${months[Number(month)-1]} ${year}` : `${day}.${month}.${year}`;
}

export function projectDay(calendar) {
  if (!calendar?.configured) return '';
  if (!calendar.project_started) return 'Проект ещё не начался';
  if (calendar.current_workday) return `${calendar.current_workday}-й рабочий день`;
  return `Выходной · прошло ${calendar.completed_workdays} раб. дн.`;
}

export function taskPeriod(task) {
  if (task.status === 'done') return 'Завершена';
  if (task.planned_start_date) return `${dateText(task.planned_start_date)} → ${dateText(task.planned_finish_date)}`;
  return `День ${task.early_start} → ${task.early_finish}`;
}

export function forecastValue(analysis) {
  return analysis?.calendar?.configured ? dateText(analysis.summary.forecast_finish_date) : analysis?.summary.project_duration ?? 0;
}
