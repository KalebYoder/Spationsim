import { useState, useEffect, useRef } from 'react'
import { useNation } from '../hooks/useNation'
import { useTutorial } from '../hooks/useTutorial'
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

function YieldTag({ value, color, suffix }) {
  if (!value && value !== 0) return null
  const sign = value > 0 ? '+' : ''
  return (
    <span style={{ fontSize: 12, color, fontVariantNumeric: 'tabular-nums' }}>
      {sign}{value}{suffix}
    </span>
  )
}

function ProductionRow({ label, value, unit, color }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, fontSize: 13 }}>
      <span style={{ color: 'var(--text-secondary)', minWidth: 110 }}>{label}</span>
      <span style={{ color, fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>{value}</span>
      <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{unit}</span>
    </div>
  )
}

function TerritoryCard({ territory, flagColor, onRenamed, yieldData, highlightProduction }) {
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
          {yieldData && (
            <span style={{ display: 'flex', gap: 10, paddingLeft: 4, borderLeft: '1px solid var(--border)' }}>
              <YieldTag value={yieldData.minerals_per_tick} color="var(--amber)" suffix=" min/t" />
              <YieldTag value={yieldData.fuel_per_tick} color="var(--teal)" suffix=" fuel/t" />
              <YieldTag
                value={yieldData.currency_net_per_tick}
                color={yieldData.currency_net_per_tick >= 0 ? 'var(--teal)' : 'var(--danger)'}
                suffix="¤/t"
              />
            </span>
          )}
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{open ? '▲' : '▼'}</span>
        </div>
      </div>

      {error && <p style={{ color: 'red', padding: '4px 20px', fontSize: 13 }}>{error}</p>}

      {open && (
        <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 20 }}>

          {yieldData && (
            <div style={highlightProduction ? {
              outline: '1px solid var(--amber)',
              borderRadius: 'var(--radius-sm)',
              padding: '8px',
            } : {}}>
              <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 10 }}>
                Production / Tick
              </div>
              <div style={{ display: 'flex', gap: 32 }}>

                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>Gains</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {yieldData.minerals_per_tick > 0 && (
                      <ProductionRow label="Minerals" value={`+${yieldData.minerals_per_tick}`} unit="min/t" color="var(--amber)" />
                    )}
                    {yieldData.fuel_per_tick > 0 && (
                      <ProductionRow label="Fuel" value={`+${yieldData.fuel_per_tick}`} unit="fuel/t" color="var(--teal)" />
                    )}
                    {yieldData.currency_income_per_tick > 0 && (
                      <ProductionRow label="Territory income" value={`+${yieldData.currency_income_per_tick}`} unit="¤/t" color="var(--teal)" />
                    )}
                    {yieldData.minerals_per_tick === 0 && yieldData.fuel_per_tick === 0 && yieldData.currency_income_per_tick === 0 && (
                      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>No active facilities</span>
                    )}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>Costs</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {yieldData.currency_upkeep_per_tick > 0 && (
                      <ProductionRow label="Fighter upkeep" value={`−${yieldData.currency_upkeep_per_tick}`} unit="¤/t" color="var(--danger)" />
                    )}
                    {yieldData.currency_upkeep_per_tick === 0 && (
                      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>None</span>
                    )}
                  </div>
                </div>

                <div style={{ borderLeft: '1px solid var(--border)', paddingLeft: 32 }}>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>Net</div>
                  <ProductionRow
                    label="Currency"
                    value={yieldData.currency_net_per_tick >= 0 ? `+${yieldData.currency_net_per_tick}` : `${yieldData.currency_net_per_tick}`}
                    unit="¤/t"
                    color={yieldData.currency_net_per_tick >= 0 ? 'var(--teal)' : 'var(--danger)'}
                  />
                </div>

              </div>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 20 }}>
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

        </div>
      )}
    </Card>
  )
}

export default function Planets() {
  const { nation, loading: nationLoading } = useNation()
  const { tutorial, completeStep3 } = useTutorial()
  const [territories, setTerritories] = useState([])
  const [yieldsById, setYieldsById] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (tutorial?.current_step === 3) {
      completeStep3()
    }
  }, [tutorial?.current_step])

  useEffect(() => {
    if (!nation) return
    Promise.all([
      fetch('/api/nations/mine/territories', { credentials: 'include' }),
      fetch('/api/nations/mine/territories/yields', { credentials: 'include' }),
    ])
      .then(([tRes, yRes]) => Promise.all([
        tRes.ok ? tRes.json() : Promise.reject(),
        yRes.ok ? yRes.json() : [],
      ]))
      .then(([tData, yData]) => {
        setTerritories(tData)
        const byId = {}
        for (const y of yData) byId[y.territory_id] = y
        setYieldsById(byId)
        setLoading(false)
      })
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
                yieldData={yieldsById[t.id] ?? null}
                highlightProduction={tutorial?.current_step === 3}
              />
            ))}
        </div>
      )}
    </div>
  )
}
