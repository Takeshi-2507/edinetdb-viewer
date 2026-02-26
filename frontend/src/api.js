const BASE = '/api'

// ---------- Device ID (端末固有識別子) ----------
function getDeviceId() {
  const KEY = 'edinet_device_id'
  let id = localStorage.getItem(KEY)
  if (!id) {
    id = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`
    localStorage.setItem(KEY, id)
  }
  return id
}

export const deviceId = getDeviceId()

// ---------- HTTP helpers ----------

async function get(path, params = {}) {
  const url = new URL(BASE + path, location.origin)
  Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v))
  const res = await fetch(url)
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
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

async function post(path, params = {}) {
  const url = new URL(BASE + path, location.origin)
  Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v))
  const res = await fetch(url, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

async function del(path, params = {}) {
  const url = new URL(BASE + path, location.origin)
  Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v))
  const res = await fetch(url, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

export const api = {
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
  alerts: () => get('/alerts', { device_id: deviceId }),
  // 米国株
  usScreener: (p) => get('/us-screener', p),
  // デモトレード（端末ごとに分離）
  demoTrades: () => get('/demo-trades', { device_id: deviceId }),
  createTrade: (trade) => postJSON('/demo-trades', { ...trade, device_id: deviceId }),
  deleteTrade: (id) => del(`/demo-trades/${id}`, { device_id: deviceId }),
  demoPortfolio: () => get('/demo-portfolio', { device_id: deviceId }),
  stockHistory: (code, period) => get(`/stock-history/${code}`, { period }),
}
