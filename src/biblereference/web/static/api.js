// Talking to the server.
//
// Two rules. Relative URLs only -- this page has to work with the network off, against a
// server on somebody's desk. And the server's error text is carried through rather than
// replaced: its refusals are written as sentences for a person ("Habakkuk has 3 chapters
// in 'eng'", "unknown languages: klingon. This machine has: cop, en, grc, hbo, la, syc"),
// and a screen that showed "Request failed" instead would be throwing away the only useful
// thing in the response.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function query(params) {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(params ?? {})) {
    if (value === null || value === undefined || value === '' || value === false) continue;
    if (Array.isArray(value)) {
      if (value.length) search.set(name, value.join(','));
    } else if (value === true) {
      search.set(name, '1');
    } else {
      search.set(name, String(value));
    }
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : '';
}

async function unwrap(response) {
  let body = null;
  try {
    body = await response.json();
  } catch {
    // A non-JSON body from a proxy or a crash. Fall through to the status line.
  }
  if (!response.ok) {
    throw new ApiError(body?.error ?? `${response.status} ${response.statusText}`, response.status);
  }
  return body;
}

/**
 * `get('/api/reader', {book: 'JHN', chapter: 3}, signal)`
 *
 * The signal comes from the router, which aborts everything in flight when the address
 * changes -- so a slow chapter cannot arrive after you have navigated away and overwrite
 * the screen you are now looking at.
 */
export async function get(path, params, signal) {
  const response = await fetch(path + query(params), { signal, headers: { Accept: 'application/json' } });
  return unwrap(response);
}

export async function post(path, body, params, signal) {
  const response = await fetch(path + query(params), {
    method: 'POST',
    body,
    signal,
    headers: { Accept: 'application/json', 'Content-Type': 'text/plain; charset=utf-8' },
  });
  return unwrap(response);
}

export const books = (params, signal) => get('/api/books', params, signal);
export const reader = (params, signal) => get('/api/reader', params, signal);
export const parse = (params, signal) => get('/api/parse', params, signal);
export const alignment = (params, signal) => get('/api/alignment', params, signal);
export const corrections = (params, signal) => get('/api/corrections', params, signal);
export const catalogue = (params, signal) => get('/api/library', params, signal);
export const families = (params, signal) => get('/api/families', params, signal);
export const search = (text, params, signal) => post('/api/search', text, params, signal);
