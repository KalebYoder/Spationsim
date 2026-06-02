import { useState, useEffect, useCallback } from 'react'
import { useLocation } from 'react-router-dom'

export function useTutorial() {
  const [tutorial, setTutorial] = useState(null)
  const location = useLocation()

  const fetch_ = useCallback(() => {
    fetch('/api/tutorial/', { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setTutorial(data) })
      .catch(() => {})
  }, [])

  useEffect(() => { fetch_() }, [fetch_, location.pathname])

  const completeStep3 = useCallback(() => {
    fetch('/api/tutorial/complete-step-3', {
      method: 'POST',
      credentials: 'include',
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setTutorial(data) })
      .catch(() => {})
  }, [])

  const completeStep9 = useCallback(() => {
    fetch('/api/tutorial/complete-step-9', {
      method: 'POST',
      credentials: 'include',
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setTutorial(data) })
      .catch(() => {})
  }, [])

  const dismiss = useCallback(() => {
    fetch('/api/tutorial/dismiss', { method: 'POST', credentials: 'include' })
      .then(() => setTutorial(t => t ? { ...t, dismissed: true } : t))
      .catch(() => {})
  }, [])

  return { tutorial, completeStep3, completeStep9, dismiss, refresh: fetch_ }
}
