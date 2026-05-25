import { useState, useEffect, useCallback } from 'react'
import { useNation } from '../hooks/useNation'
import { Card, SectionLabel, EmptyState, Tr, Td, Badge, Btn, StatCard } from '../components/ui'

const FACILITY_TYPES = [
  { value: 'mine',            label: 'Mine',            cost: { minerals: 20, fuel:  10 } },
  { value: 'refinery',        label: 'Refinery',        cost: { minerals: 10, fuel:  20 } },
  { value: 'shipyard', label: 'Shipyard', cost: { minerals: 50, fuel: 20 } },
  { value: 'probe_factory',   label: 'Probe Factory',   cost: { minerals: 10, fuel:   5 } },
]

function BuildForm({ territories, nation, onBuilt }) {
  const [territoryId, setTerritoryId] = useState(territories[0]?.id ?? '')
  const [type, setType] = useState('mine')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const selected = FACILITY_TYPES.find(f => f.value === type)
  const canAfford = nation.minerals >= selected.cost.minerals && nation.fuel >= selected.cost.fuel

  const handleBuild = async () => {
    setSubmitting(true)
    setError('')
    try {
      const r = await fetch('/api/facilities', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ territory_id: Number(territoryId), type }),
      })
      const data = await r.json()
      if (!r.ok) { setError(data.detail || 'Build failed'); return }
      onBuilt(data)
    } catch {
      setError('Network error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Territory</div>
          <select
            value={territoryId}
            onChange={e => setTerritoryId(e.target.value)}
            style={{ padding: '6px 10px', background: 'var(--bg-base)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}
          >
            {territories.map(t => (
              <option key={t.id} value={t.id}>{t.name || t.node_key}</option>
            ))}
          </select>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Type</div>
          <select
            value={type}
            onChange={e => setType(e.target.value)}
            style={{ padding: '6px 10px', background: 'var(--bg-base)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}
          >
            {FACILITY_TYPES.map(f => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', paddingBottom: 2 }}>
          Cost: <span style={{ color: canAfford ? 'var(--text-primary)' : 'var(--danger)' }}>
            {selected.cost.minerals} minerals, {selected.cost.fuel} fuel
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8, paddingBottom: 2 }}>
          <Btn variant="amber" onClick={handleBuild} disabled={submitting || !canAfford}>
            {submitting ? 'Building…' : 'Build'}
          </Btn>
        </div>
      </div>
      {error && <p style={{ color: 'var(--danger)', fontSize: 13, marginTop: 10 }}>{error}</p>}
      {!canAfford && (
        <p style={{ color: 'var(--danger)', fontSize: 13, marginTop: 10 }}>Insufficient resources</p>
      )}
    </Card>
  )
}

export default function Facilities() {
  const { nation: initialNation, loading: nationLoading } = useNation()
  const [nation, setNation] = useState(null)
  const [facilities, setFacilities] = useState([])
  const [territories, setTerritories] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sortKey, setSortKey] = useState(null)
  const [sortAsc, setSortAsc] = useState(true)

  useEffect(() => {
    if (initialNation) setNation(initialNation)
  }, [initialNation])

  const load = useCallback(async () => {
    try {
      const [fRes, tRes, nRes] = await Promise.all([
        fetch('/api/facilities', { credentials: 'include' }),
        fetch('/api/nations/mine/territories', { credentials: 'include' }),
        fetch('/api/nations/mine', { credentials: 'include' }),
      ])
      const [f, t, n] = await Promise.all([fRes.json(), tRes.json(), nRes.json()])
      setFacilities(f)
      setTerritories(t)
      setNation(n)
    } catch {
      setError('Failed to load facilities')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (!nationLoading) load() }, [nationLoading])

  const handleBuilt = newFacility => {
    setFacilities(fs => [...fs, newFacility])
    load()
  }

  if (nationLoading || loading) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  const typeLabel = { mine: 'Mine', refinery: 'Refinery', shipyard: 'Shipyard', probe_factory: 'Probe Factory' }

  const COLUMNS = [
    { key: 'type',      label: 'Type',      compare: (a, b) => (typeLabel[a.type] || a.type).localeCompare(typeLabel[b.type] || b.type) },
    { key: 'territory', label: 'Territory', compare: (a, b) => (a.territory_name || a.territory_node_key).localeCompare(b.territory_name || b.territory_node_key) },
    { key: 'level',     label: 'Level',     compare: (a, b) => a.level - b.level },
    { key: 'built',     label: 'Built',     compare: (a, b) => (a.built_at || '').localeCompare(b.built_at || '') },
  ]

  const handleSort = key => {
    if (sortKey === key) setSortAsc(a => !a)
    else { setSortKey(key); setSortAsc(true) }
  }

  const sortedFacilities = sortKey
    ? [...facilities].sort((a, b) => {
        const col = COLUMNS.find(c => c.key === sortKey)
        return sortAsc ? col.compare(a, b) : col.compare(b, a)
      })
    : facilities

  return (
    <div>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 22, fontWeight: 600 }}>Facilities</h1>
        <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
          All infrastructure across your empire
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 14, marginBottom: 28 }}>
        <StatCard label="Total Facilities" value={facilities.length} />
        <StatCard label="Minerals" value={nation ? parseFloat(nation.minerals).toFixed(0) : '—'} accent="var(--amber)" />
        <StatCard label="Fuel" value={nation ? parseFloat(nation.fuel).toFixed(0) : '—'} accent="var(--teal)" />
      </div>

      {territories.length > 0 && (
        <BuildForm territories={territories} nation={nation} onBuilt={handleBuilt} />
      )}

      <SectionLabel>All Facilities</SectionLabel>

      {error && <p style={{ color: 'var(--danger)' }}>{error}</p>}

      <Card style={{ padding: 0 }}>
        {facilities.length === 0 ? (
          <EmptyState
            title="No facilities built"
            body="Build infrastructure on your colonized territories to start generating resources."
          />
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {COLUMNS.map(col => (
                    <th
                      key={col.key}
                      onClick={() => handleSort(col.key)}
                      style={{
                        textAlign: 'left',
                        padding: '8px 14px',
                        fontSize: 11,
                        textTransform: 'uppercase',
                        letterSpacing: '0.08em',
                        color: sortKey === col.key ? 'var(--text-primary)' : 'var(--text-muted)',
                        borderBottom: '1px solid var(--border)',
                        cursor: 'pointer',
                        userSelect: 'none',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {col.label}
                      {sortKey === col.key && (
                        <span style={{ marginLeft: 4 }}>{sortAsc ? '↑' : '↓'}</span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedFacilities.map(f => (
                  <Tr key={f.id}>
                    <Td><Badge color={f.type === 'mine' ? 'amber' : 'teal'}>{typeLabel[f.type] || f.type}</Badge></Td>
                    <Td>{f.territory_name || f.territory_node_key}</Td>
                    <Td muted>{f.level}</Td>
                    <Td muted>{f.built_at ? new Date(f.built_at).toLocaleDateString() : '—'}</Td>
                  </Tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
