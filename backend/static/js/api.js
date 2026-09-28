// Same-origin API; the UI never performs scheduling calculations itself.
export async function request(path, {method = 'GET', body, signal} = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: {'Content-Type': 'application/json'},
      ...(body !== undefined ? {body: JSON.stringify(body)} : {}),
      signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('Не удалось связаться с сервером. Проверьте подключение и повторите действие.');
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(data?.error || `Ошибка сервера: ${response.status}`);
    error.status = response.status; error.code = data?.code;
    throw error;
  }
  if (data === null) throw new Error('Сервер вернул некорректный ответ. Обновите страницу.');
  return data;
}
export const projectPath = (id, suffix = '') => `/api/projects/${encodeURIComponent(id)}${suffix}`;
