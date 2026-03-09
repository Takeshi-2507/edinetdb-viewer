import { useState } from 'react'
import { api, setToken } from '../api'

export default function Login({ onLogin }) {
  const [userId, setUserId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await api.login(userId, password)
      setToken(res.token)
      onLogin(res.user_id)
    } catch (err) {
      setError(err.message || 'ログインに失敗しました')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg)',
    }}>
      <form onSubmit={handleSubmit} style={{
        width: '100%', maxWidth: 360, padding: 32,
        background: 'var(--surface)', borderRadius: 12,
        border: '1px solid var(--border)',
      }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--accent)' }}>
            SnowWillow Terminal
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 4 }}>
            EDINET DB Viewer
          </div>
        </div>

        {error && (
          <div style={{
            padding: '8px 12px', marginBottom: 16, borderRadius: 6, fontSize: 12,
            background: 'rgba(239,68,68,0.1)', color: 'var(--red)', border: '1px solid var(--red)',
          }}>
            {error}
          </div>
        )}

        <label style={{ display: 'block', marginBottom: 12 }}>
          <span style={{ fontSize: 12, color: 'var(--text-dim)', display: 'block', marginBottom: 4 }}>
            User ID
          </span>
          <input
            type="text" value={userId} onChange={e => setUserId(e.target.value)}
            autoComplete="username" autoFocus required
            style={{ width: '100%', padding: '10px 12px', fontSize: 14 }}
          />
        </label>

        <label style={{ display: 'block', marginBottom: 20 }}>
          <span style={{ fontSize: 12, color: 'var(--text-dim)', display: 'block', marginBottom: 4 }}>
            Password
          </span>
          <input
            type="password" value={password} onChange={e => setPassword(e.target.value)}
            autoComplete="current-password" required
            style={{ width: '100%', padding: '10px 12px', fontSize: 14 }}
          />
        </label>

        <button type="submit" disabled={loading} style={{
          width: '100%', padding: '12px', borderRadius: 8,
          background: 'var(--accent)', color: '#fff', border: 'none',
          fontWeight: 700, fontSize: 14, cursor: loading ? 'wait' : 'pointer',
          opacity: loading ? 0.7 : 1,
        }}>
          {loading ? 'ログイン中...' : 'ログイン'}
        </button>
      </form>
    </div>
  )
}
