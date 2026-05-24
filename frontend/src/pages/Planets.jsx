import { useState, useEffect, useRef } from 'react'
import { useNation } from '../hooks/useNation'
import { Card, SectionLabel, EmptyState, Badge, Btn } from '../components/ui'

function RenameInput({ current, onSave, onCancel }) {
  const [value, setValue] = useState(current)
  const inputRef = useRef(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  const submit = () => {
    const trimmed = value.trim()
    if (trimmed && trimmed !== current) onSave(trimmed)
    else onCancel()
  }

  const onKey = e => {
    if (e.key === 'Enter') submit()
    if (e.key === 'Escape') onCancel()
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <input
        ref={inputRef}
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={onKey}
        maxLength={128}
        style={{ fontSize: 15, fontWeight: 500, padding: '2px 8px', width: 220 }}
      />
      <Btn variant="amber" onClick={submit} style={{ padding: '2px 10px', fontSize: 12 }}>Save</Btn>
      <Btn onClick={onCancel} style={{ padding: '2px 10px', fontSize: 12 }}>Cancel</Btn>
    </div>
  )
}

function TerritoryCard({ territory, flagColor, onRenamed }) {
  const [open, setOpen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const displayName = territory.name || territory.node_key

  const handleSave = async newName => {
    setSaving(true)
    setError('')
    try {
      const r = await fetch(`/api/territories/${territory.id}/name`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName }),
      })
      if (!r.ok) {
        const err = await r.json()
        setError(err.detail || 'Failed to rename')
        return
      }
      const updated = await r.json()
      onRenamed(updated)
    } catch {
      setError('Network error')
    } finally {
      setSaving(false)
      setRenaming(false)
    }
  }

  return (
    <Card style={{ padding: 0, overflow: 'hidden' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '14px 20px',
          background: open ? 'var(--bg-hover)' : 'transparent',
          borderBottom: open ? '1px solid var(--border)' : 'none',
          transition: 'background 0.15s',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{
            display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
            background: flagColor || 'var(--teal)', flexShrink: 0,
          }} />
          {renaming ? (
            <RenameInput
              current={territory.name || ''}
              onSave={handleSave}
              onCancel={() => setRenaming(false)}
            />
          ) : (
            <>
              <span
                style={{ fontWeight: 500, cursor: 'pointer' }}
                onClick={() => setOpen(o => !o)}
              >
                {displayName}
              </span>
              {territory.name && (
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{territory.node_key}</span>
              )}
              {!saving && (
                <button
                  onClick={() => setRenaming(true)}
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: 'var(--text-muted)', fontSize: 12, padding: '0 4px',
                  }}
                  title="Rename"
                >
                  ✎
                </button>
              )}
            </>
          )}
          {territory.is_home && <Badge color="teal">Home</Badge>}
        </div>
        <div
          onClick={() => setOpen(o => !o)}
          style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 13, color: 'var(--text-secondary)', cursor: 'pointer' }}
        >
          <span>Distance {territory.distance_from_center}</span>
          <span>Min {parseFloat(territory.mineral_richness).toFixed(2)}</span>
          <span>Fuel {parseFloat(territory.fuel_richness).toFixed(2)}</span>
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{open ? '▲' : '▼'}</span>
        </div>
      </div>

      {error && <p style={{ color: 'red', padding: '4px 20px', fontSize: 13 }}>{error}</p>}

      {open && (
        <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 20 }}>
          <div>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 8 }}>
              Population
            </div>
            <EmptyState title="—" body="No population data yet" />
          </div>
          <div>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 8 }}>
              Facilities
            </div>
            <EmptyState title="None built" body="Build facilities from the Facilities page" />
          </div>
          <div>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 8 }}>
              Stationed Military
            </div>
            <EmptyState title="None" body="Station fleets from the Military page" />
          </div>
        </div>
      )}
    </Card>
  )
}

export default function Planets() {
  const { nation, loading: nationLoading } = useNation()
  const [territories, setTerritories] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!nation) return
    fetch('/api/nations/mine/territories', { credentials: 'include' })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => { setTerritories(data); setLoading(false) })
      .catch(() => { setError('Failed to load territories'); setLoading(false) })
  }, [nation?.id])

  const handleRenamed = updated => {
    setTerritories(ts => ts.map(t => t.id === updated.id ? { ...t, name: updated.name } : t))
  }

  if (nationLoading || loading) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  const territoriesWithHome = territories.map(t => ({
    ...t,
    is_home: t.id === nation?.home_territory_id,
  }))

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600 }}>Planets</h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
            Per-territory breakdown of population, facilities, and military
          </p>
        </div>
        <Btn variant="amber" disabled>Send Colony Ship</Btn>
      </div>

      <SectionLabel>Your Territories</SectionLabel>

      {error && <p style={{ color: 'red' }}>{error}</p>}

      {territories.length === 0 && !error ? (
        <Card>
          <EmptyState title="No territories" body="Create your nation to claim a home system." />
        </Card>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {territoriesWithHome
            .sort((a, b) => b.is_home - a.is_home)
            .map(t => (
              <TerritoryCard
                key={t.id}
                territory={t}
                flagColor={nation?.flag_color}
                onRenamed={handleRenamed}
              />
            ))}
        </div>
      )}
    </div>
  )
}
