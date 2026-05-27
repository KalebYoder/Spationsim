import { useState, useEffect } from 'react'

export function diploColor(status) {
  if (status === 'war' || status === 'war_pending')       return '#c0726a'
  if (status === 'friendly' || status === 'friend_pending') return '#6aab72'
  return '#b8a98a'
}

export function useDiplomacy() {
  const [byId, setById] = useState({})

  useEffect(() => {
    fetch('/api/diplomacy/relations', { credentials: 'include' })
      .then(r => r.ok ? r.json() : [])
      .then(data => {
        const map = {}
        for (const rel of data) map[rel.nation_id] = rel.status
        setById(map)
      })
      .catch(() => {})
  }, [])

  return {
    statusOf: (nationId) => byId[nationId] ?? 'neutral',
    colorOf:  (nationId) => diploColor(byId[nationId] ?? 'neutral'),
  }
}
