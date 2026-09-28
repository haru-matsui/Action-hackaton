import {dateText} from './dates.js';

export function parseDateInput(value, required = false) {
  const text = value.trim();
  if (!text) return {iso:null, error:required ? 'Укажите дату начала проекта.' : ''};
  let year, month, day;
  let match = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(text);
  if (match) [,day,month,year] = match;
  else if ((match = /^(\d{2})(\d{2})(\d{4})$/.exec(text))) [,day,month,year] = match;
  else if ((match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text))) [,year,month,day] = match;
  else return {iso:null,error:'Введите дату в формате ДД.ММ.ГГГГ, например 28.09.2026.'};
  const y = Number(year), m = Number(month), d = Number(day);
  const check = new Date(Date.UTC(y,m-1,d));
  if (check.getUTCFullYear() !== y || check.getUTCMonth() !== m-1 || check.getUTCDate() !== d) {
    return {iso:null,error:'Такой даты не существует. Проверьте день и месяц.'};
  }
  if (y < 2000 || y > 2100) return {iso:null,error:'Укажите год с 2000 по 2100.'};
  return {iso:`${year}-${String(m).padStart(2,'0')}-${String(d).padStart(2,'0')}`,error:''};
}

export function dateRange(start, deadline, {today, existingStart} = {}) {
  const first = parseDateInput(start,true), last = parseDateInput(deadline);
  if (!first.error && today && first.iso < today && first.iso !== existingStart) {
    first.error = 'Дата начала не может быть раньше сегодняшней.';
  }
  if (!first.error && !last.error && last.iso && last.iso < first.iso) {
    last.error = 'Дедлайн не может быть раньше начала проекта.';
  }
  return {start:first,deadline:last,valid:!first.error && !last.error};
}

export function setDateField(input, picker, iso) {
  input.value = iso ? dateText(iso) : '';
  picker.value = iso || '';
  input.setCustomValidity('');
}

export function calendarMonth(year, month) {
  const first = new Date(Date.UTC(year,month,1));
  const count = new Date(Date.UTC(year,month+1,0)).getUTCDate();
  return {year:first.getUTCFullYear(), month:first.getUTCMonth(),
    padding:(first.getUTCDay()+6)%7,
    label:first.toLocaleDateString('ru-RU',{month:'long',year:'numeric',timeZone:'UTC'}),
    days:Array.from({length:count},(_,i) => ({day:i+1,iso:`${first.getUTCFullYear()}-${String(first.getUTCMonth()+1).padStart(2,'0')}-${String(i+1).padStart(2,'0')}`}))};
}

export function bindDateField(input, picker, button, changed) {
  // Never mask or rewrite text on input: selection, caret and Backspace stay native.
  input.addEventListener('input', () => { input.setCustomValidity(''); changed(); });
  input.addEventListener('blur', () => {
    const parsed = parseDateInput(input.value, input.required);
    input.setCustomValidity(parsed.error);
    if (!parsed.error) setDateField(input,picker,parsed.iso);
  });
  picker.addEventListener('change', () => {
    setDateField(input,picker,picker.value);
    changed(); input.focus();
  });
  let popup, year, month;
  const close = (focus = false) => {
    if (!popup) return;
    popup.remove(); popup = null; button.setAttribute('aria-expanded','false');
    if (focus) button.focus();
  };
  const render = focusDate => {
    const page = calendarMonth(year,month);
    year = page.year; month = page.month;
    const min = picker.min || '2000-01-01', max = picker.max || '2100-12-31';
    const selected = parseDateInput(input.value).iso;
    const previous = calendarMonth(year,month-1), next = calendarMonth(year,month+1);
    popup.innerHTML = `<div class="calendar-picker-heading"><button type="button" data-month="-1" aria-label="Предыдущий месяц" ${previous.days.at(-1).iso < min ? 'disabled' : ''}>‹</button><strong aria-live="polite">${page.label}</strong><button type="button" data-month="1" aria-label="Следующий месяц" ${next.days[0].iso > max ? 'disabled' : ''}>›</button></div><div class="calendar-picker-grid">${['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(day=>`<span class="calendar-weekday">${day}</span>`).join('')}${'<span></span>'.repeat(page.padding)}${page.days.map(day=>`<button type="button" data-date="${day.iso}" aria-label="${dateText(day.iso)}" aria-pressed="${day.iso === selected}" ${day.iso < min || day.iso > max ? 'disabled' : ''}>${day.day}</button>`).join('')}</div>`;
    if (focusDate) popup.querySelector(`[data-date="${focusDate}"]:not(:disabled)`)?.focus();
  };
  button.setAttribute?.('aria-expanded','false');
  button.addEventListener('click', event => {
    event.preventDefault();
    if (popup) { close(); return; }
    const initial = parseDateInput(input.value).iso || picker.min || '2000-01-01';
    [year,month] = initial.split('-').map(Number); month--;
    popup = input.ownerDocument.createElement('div');
    popup.className = 'calendar-picker';
    popup.setAttribute('role','group'); popup.setAttribute('aria-label','Выбор даты');
    // An inline picker stays inside the dialog on small screens as well.
    input.closest('.dialog-body').append(popup);
    button.setAttribute('aria-expanded','true');
    render();
    popup.addEventListener('click', event => {
      const target = event.target.closest('button');
      if (!target || target.disabled) return;
      event.preventDefault();
      if (target.dataset.month) { month += Number(target.dataset.month); render(); return; }
      if (target.dataset.date) {
        setDateField(input,picker,target.dataset.date); changed(); close(); input.focus();
      }
    });
    popup.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); return; }
      const current = event.target.dataset.date;
      const move = {ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7}[event.key];
      if (!current || !move) return;
      event.preventDefault();
      const day = new Date(current + 'T00:00:00Z'); day.setUTCDate(day.getUTCDate()+move);
      const iso = day.toISOString().slice(0,10);
      if (iso < (picker.min || '2000-01-01') || iso > (picker.max || '2100-12-31')) return;
      year = day.getUTCFullYear(); month = day.getUTCMonth(); render(iso);
    });
  });
  input.ownerDocument?.addEventListener('pointerdown', event => {
    if (popup && !popup.contains(event.target) && !button.contains(event.target)) close();
  });
  input.closest?.('dialog')?.addEventListener('close', () => close());
}
