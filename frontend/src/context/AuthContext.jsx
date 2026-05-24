import { createContext, useContext, useState, useEffect } from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [player, setPlayer] = useState(undefined) // undefined = loading

  useEffect(() => {
    fetch('/api/auth/me', { credentials: 'include' })
      .then(r => (r.ok ? r.json() : null))
      .then(data => setPlayer(data))
      .catch(() => setPlayer(null))
  }, [])

  const login = async (username, password) => {
    const r = await fetch('/api/auth/login', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!r.ok) {
      const err = await r.json()
      throw new Error(err.detail || 'Login failed')
    }
    const data = await r.json()
    setPlayer(data)
    return data
  }

  const register = async (username, email, password) => {
    const r = await fetch('/api/auth/register', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password }),
    })
    if (!r.ok) {
      const err = await r.json()
      throw new Error(err.detail || 'Registration failed')
    }
    const data = await r.json()
    setPlayer(data)
    return data
  }

  const logout = async () => {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
    setPlayer(null)
  }

  return (
    <AuthContext.Provider value={{ player, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
