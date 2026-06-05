import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'

export default function NationSearch() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [nations, setNations] = useState(null)
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)
  const containerRef = useRef(null)
  const inputRef = useRef(null)

  const loadNations = useCallback(() => {
    if (nations !== null) return
    fetch('/api/nations', { credentials: 'include' })
      .then(r => r.ok ? r.json() : [])
      .then(data => setNations(data))
      .catch(() => setNations([]))
  }, [nations])

  const results = !query.trim() || !nations
    ? []
    : nations
        .filter(n => n.name.toLowerCase().includes(query.toLowerCase()))
        .slice(0, 8)

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false)
        setActiveIdx(-1)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const select = (id) => {
    navigate(`/nations/${id}`)
    setQuery('')
    setOpen(false)
    setActiveIdx(-1)
    inputRef.current?.blur()
  }

  const handleKeyDown = (e) => {
    if (!open || results.length === 0) {
      if (e.key === 'Escape') { setQuery(''); setOpen(false) }
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      if (activeIdx >= 0) select(results[activeIdx].id)
    } else if (e.key === 'Escape') {
      setOpen(false)
      setActiveIdx(-1)
    }
  }

  return (
    <div ref={containerRef} style={{ position: 'relative', width: 220 }}>
      <input
        ref={inputRef}
        value={query}
        placeholder="Search nations…"
        onFocus={() => { loadNations(); if (query.trim()) setOpen(true) }}
        onChange={e => { setQuery(e.target.value); setOpen(true); setActiveIdx(-1) }}
        onKeyDown={handleKeyDown}
        style={{
          width: '100%',
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)',
          color: 'var(--text-primary)',
          padding: '6px 10px',
          fontSize: 13,
          outline: 'none',
        }}
      />

      {open && results.length > 0 && (
        <div style={{
          position: 'absolute',
          top: 'calc(100% + 4px)',
          left: 0,
          right: 0,
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)',
          boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
          zIndex: 200,
          overflow: 'hidden',
        }}>
          {results.map((n, i) => (
            <button
              key={n.id}
              onMouseDown={() => select(n.id)}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '8px 12px',
                background: i === activeIdx ? 'var(--bg-hover)' : 'transparent',
                color: i === activeIdx ? 'var(--text-primary)' : 'var(--text-secondary)',
                fontSize: 13,
                borderBottom: i < results.length - 1 ? '1px solid var(--border)' : 'none',
                cursor: 'pointer',
              }}
              onMouseEnter={() => setActiveIdx(i)}
            >
              {n.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
