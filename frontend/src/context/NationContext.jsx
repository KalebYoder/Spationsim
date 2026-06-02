import { createContext, useContext, useState, useEffect } from 'react'

const NationContext = createContext(null)

export function NationProvider({ children }) {
  const [nation, setNation] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/api/nations/mine', { credentials: 'include' })
      .then(r => (r.ok ? r.json() : null))
      .then(data => { setNation(data); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [])

  return (
    <NationContext.Provider value={{ nation, loading, error, setNation }}>
      {children}
    </NationContext.Provider>
  )
}

export const useNationContext = () => useContext(NationContext)
