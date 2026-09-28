// Shared presentation helpers. No network calls or project mutations here.
export const $ = selector => document.querySelector(selector);
export const $$ = selector => [...document.querySelectorAll(selector)];
export const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

const paths = {
  users: '<circle cx="9" cy="7" r="3"/><path d="M3 21v-2a6 6 0 0 1 12 0v2M16 4a3 3 0 0 1 0 6M21 21v-2a6 6 0 0 0-4-5.7"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8ZM14 2v6h6M8 13h8M8 17h5"/>',
  link: '<path d="m10 13 4-4M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0M16 8l1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0" transform="translate(0 -1)"/>',
  radar: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="m12 12 7-7"/><circle cx="12" cy="12" r="1"/>',
  folder: '<path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  layout: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  list: '<path d="M9 6h12M9 12h12M9 18h12"/><rect x="3" y="5" width="2" height="2" rx=".5"/><rect x="3" y="11" width="2" height="2" rx=".5"/><rect x="3" y="17" width="2" height="2" rx=".5"/>',
  branches: '<rect x="9" y="2" width="6" height="5" rx="1.5"/><rect x="2" y="17" width="6" height="5" rx="1.5"/><rect x="16" y="17" width="6" height="5" rx="1.5"/><path d="M12 7v5M5 17v-5h14v5"/>',
  sparkles: '<path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4Z M20 2v4M18 4h4"/>',
  shield: '<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6Z"/><path d="m8 12 3 3 5-6"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  reset: '<path d="M3 10a9 9 0 1 1 1 8M3 4v6h6"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18M7 14h2M13 14h2"/>',
  timeline: '<path d="M3 4v16M7 6h7M10 12h10M16 18h5"/>',
  flask: '<path d="M9 3h6M10 3v6l-6 10a1.4 1.4 0 0 0 1 2h14a1.4 1.4 0 0 0 1-2L14 9V3M7 15h10"/>',
  mouse: '<rect x="6" y="2" width="12" height="20" rx="6"/><path d="M12 6v4"/>',
  arrowRight: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  arrowUpRight: '<path d="M6 18 18 6M6 6h12v12"/>',
  arrowUp: '<path d="M12 20V4m-6 6 6-6 6 6"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  flag: '<path d="M5 21V3c5-3 9 3 14 0v11c-5 3-9-3-14 0"/>',
  alert: '<path d="M10.4 3.6 2.1 18a2 2 0 0 0 1.7 3h16.4a2 2 0 0 0 1.7-3L13.6 3.6a1.8 1.8 0 0 0-3.2 0Z"/><path d="M12 9v4M12 17h.01"/>',
  activity: '<path d="M2 12h5l3-8 4 16 3-8h5"/>',
  route: '<circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><path d="M7 5h9a4 4 0 0 1 0 8H8a3 3 0 0 0 0 6h9"/>',
  download: '<path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/>',
  x: '<path d="m6 6 12 12M6 18 18 6"/>',
  edit: '<path d="m16 3 5 5-12 12-6 1 1-6ZM13 6l5 5"/>',
};
export function icon(name, extraClass = '') {
  return `<svg class="icon ${extraClass}" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.sparkles}</svg>`;
}
export function hydrateIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach(node => { node.innerHTML = icon(node.dataset.icon); });
}
const palette = [['#eee9f6','#9b87b4'],['#e7f0ec','#7a9e8f'],['#f4ebdf','#b19a79'],['#e6ecf6','#8a9ebc'],['#f5e7ed','#b48f9e']];
export function avatar(name) {
  const index = [...name].reduce((sum, char) => sum + char.charCodeAt(0), 0) % palette.length;
  const letters = name.trim().split(/\s+/).slice(0, 2).map(s => s[0]).join('').toUpperCase() || '—';
  return `<span class="avatar" style="--avatar-bg:${palette[index][0]};--avatar-fg:${palette[index][1]}" title="${escapeHTML(name)}" aria-label="${escapeHTML(name)}">${escapeHTML(letters)}</span>`;
}
export function richText(text) {
  return String(text ?? '').split(/\n\s*\n/).filter(Boolean).map(paragraph => `<p>${escapeHTML(paragraph).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>')}</p>`).join('');
}
export function toast(message, error = false) {
  const node = document.createElement('div');
  node.className = `toast${error ? ' error' : ''}`;
  node.setAttribute('role', error ? 'alert' : 'status');
  node.innerHTML = icon(error ? 'alert' : 'checkCircle') + `<span>${escapeHTML(message)}</span>`;
  const dialog = [...document.querySelectorAll('dialog[open]')].at(-1);
  if (dialog) {
    node.classList.add('dialog-toast');
    (dialog.querySelector('form') || dialog).append(node);
    node.scrollIntoView({block:'nearest'});
  } else $('#toasts').append(node);
  setTimeout(() => node.remove(), error ? 7000 : 4000);
}
export async function busy(button, action) {
  if (button?.disabled) return;
  if (button) { button.disabled = true; button.setAttribute('aria-busy', 'true'); }
  try { return await action(); }
  catch (error) { if (error.name !== 'AbortError') toast(error.message || 'Не удалось выполнить действие', true); }
  finally { if (button) { button.disabled = false; button.removeAttribute('aria-busy'); } }
}
export function confirmAction(title, text, acceptLabel = 'Удалить') {
  const dialog = $('#confirmDialog');
  $('#confirmTitle').textContent = title;
  $('#confirmText').textContent = text;
  $('#confirmAccept').textContent = acceptLabel;
  dialog.showModal();
  $('#confirmCancel').focus();
  return new Promise(resolve => {
    let confirmed = false;
    $('#confirmAccept').onclick = () => { confirmed = true; dialog.close(); };
    $('#confirmCancel').onclick = () => dialog.close();
    dialog.addEventListener('close', () => resolve(confirmed), {once:true});
  });
}
export function emptyState(title, description, action = '') {
  return `<div class="empty-state">${icon('folder')}<h3>${escapeHTML(title)}</h3><p>${escapeHTML(description)}</p>${action}</div>`;
}
export const statusNames = {todo:'К выполнению', in_progress:'В работе', done:'Выполнено'};
export const statusPill = status => `<span class="status-pill ${escapeHTML(status)}">${statusNames[status] || 'К выполнению'}</span>`;
export const signed = number => `${number > 0 ? '+' : ''}${number}`;
export function aiNotice(data) {
  if (!data?.ai || data.ai.source === 'llm' || data.ai.source === 'pending') return '';
  return `<div class="ai-notice">${icon('alert')}<span>ИИ временно недоступен. Показана сводка по данным проекта.</span></div>`;
}
export function plural(number, one, few, many) {
  const last = Math.abs(number) % 100;
  return last >= 11 && last <= 14 ? many : last % 10 === 1 ? one : last % 10 >= 2 && last % 10 <= 4 ? few : many;
}
