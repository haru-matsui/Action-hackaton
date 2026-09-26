// Same-origin API; the UI never performs scheduling calculations itself.
export async function request(path, {method = 'GET', body, signal} = {}) {
  const response = await fetch(path, {
    method,
    headers: {'Content-Type': 'application/json'},
    ...(body !== undefined ? {body: JSON.stringify(body)} : {}),
    signal,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.error || `Ошибка сервера: ${response.status}`);
  if (data === null) throw new Error('Сервер вернул некорректный ответ. Обновите страницу.');
  return data;
}
export const projectPath = (id, suffix = '') => `/api/projects/${encodeURIComponent(id)}${suffix}`;
