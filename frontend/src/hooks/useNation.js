import { useState, useEffect } from 'react'

export function useNation() {
  const [nation, setNation] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/api/nations/mine', { credentials: 'include' })
      .then(r => (r.ok ? r.json() : null))
      .then(data => { setNation(data); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [])

  return { nation, loading, error }
}
