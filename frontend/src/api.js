const BASE = '/api'
const TOKEN_KEY = 'edinet_auth_token'

// ---------- Auth helpers ----------
export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

// ---------- HTTP helpers ----------

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function get(path, params = {}) {
  const url = new URL(BASE + path, location.origin)
  Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v))
  const res = await fetch(url, { headers: authHeaders() })
  if (res.status === 401) {
    clearToken()
    window.location.href = '/login'
    throw new Error('認証が必要です')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

async function postJSON(path, body = {}) {
  const url = new URL(BASE + path, location.origin)
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (res.status === 401) {
    clearToken()
    window.location.href = '/login'
    throw new Error('認証が必要です')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

async function post(path, params = {}) {
  const url = new URL(BASE + path, location.origin)
  Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v))
  const res = await fetch(url, { method: 'POST', headers: authHeaders() })
  if (res.status === 401) {
    clearToken()
    window.location.href = '/login'
    throw new Error('認証が必要です')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

async function del(path, params = {}) {
  const url = new URL(BASE + path, location.origin)
  Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v))
  const res = await fetch(url, { method: 'DELETE', headers: authHeaders() })
  if (res.status === 401) {
    clearToken()
    window.location.href = '/login'
    throw new Error('認証が必要です')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

export const api = {
  // 認証
  login: (user_id, password) => postJSON('/auth/login', { user_id, password }),
  me: () => get('/auth/me'),
  // 公開API
  status: () => get('/status'),
  companies: (p) => get('/companies', p),
  company: (id) => get(`/companies/${id}`),
  financials: (id) => get(`/companies/${id}/financials`),
  companyIr: (id) => get(`/companies/${id}/ir`),
  ranking: (metric, p) => get(`/rankings/${metric}`, p),
  industries: () => get('/industries'),
  syncLog: () => get('/sync-log'),
  screener: (p) => get('/screener', p),
  price: (code) => get(`/price/${code}`),
  prices: (codes) => get('/prices', { codes }),
  tags: () => get('/tags'),
  addTag: (edinetCode, tag) => post(`/tags/${edinetCode}`, { tag }),
  removeTag: (edinetCode, tag) => del(`/tags/${edinetCode}`, { tag }),
  // 検索・アラート
  companySearch: (q) => get('/company-search', { q }),
  alerts: () => get('/alerts'),
  // 米国株
  usScreener: (p) => get('/us-screener', p),
  // デモトレード（ユーザーごと）
  demoTrades: () => get('/demo-trades'),
  createTrade: (trade) => postJSON('/demo-trades', trade),
  deleteTrade: (id) => del(`/demo-trades/${id}`),
  demoPortfolio: () => get('/demo-portfolio'),
  stockHistory: (code, period) => get(`/stock-history/${code}`, { period }),
}
