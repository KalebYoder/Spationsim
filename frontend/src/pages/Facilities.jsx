import { useState, useEffect, useCallback } from 'react'
import { useNation } from '../hooks/useNation'
import { Card, SectionLabel, EmptyState, Tr, Td, Badge, Btn, StatCard } from '../components/ui'

const FACILITY_TYPES = [
  { value: 'mine',               label: 'Mine',               cost: { minerals:  60, fuel:  30, currency:  500 }, buildTicks: 1 },
  { value: 'refinery',           label: 'Refinery',           cost: { minerals:  30, fuel:  60, currency:  500 }, buildTicks: 1 },
  { value: 'shipyard',           label: 'Shipyard',           cost: { minerals: 150, fuel:  60, currency: 2000 }, buildTicks: 2 },
  { value: 'propaganda_office',  label: 'Propaganda Office',  cost: { minerals: 500, fuel: 250, currency: 6000 }, buildTicks: 2 },
]

const TYPE_LABEL = { mine: 'Mine', refinery: 'Refinery', shipyard: 'Shipyard', propaganda_office: 'Propaganda Office' }

function statusBadgeColor(status) {
  if (status === 'active') return 'teal'
  if (status === 'under_construction') return 'amber'
  return 'danger'
}

function statusLabel(status) {
  if (status === 'active') return 'Active'
  if (status === 'under_construction') return 'Building'
  if (status === 'demolishing') return 'Demolishing'
  return status
}

function CountdownCell({ isoTs }) {
  const end = new Date(isoTs).getTime()
  const now = Date.now()
  const ms = end - now
  if (ms <= 0) return <span style={{ color: 'var(--teal)' }}>this tick</span>
  const h = Math.floor(ms / 3_600_000)
  const m = Math.floor((ms % 3_600_000) / 60_000)
  return <span style={{ color: 'var(--text-muted)' }}>{h}h {m}m</span>
}

function BuildForm({ territories, nation, onBuilt }) {
  const [territoryId, setTerritoryId] = useState(territories[0]?.id ?? '')
  const [type, setType] = useState('mine')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const selected = FACILITY_TYPES.find(f => f.value === type)
  const canAfford = nation.minerals >= selected.cost.minerals && nation.fuel >= selected.cost.fuel && (nation.currency ?? 0) >= (selected.cost.currency ?? 0)

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
          <div>Cost: <span style={{ color: canAfford ? 'var(--text-primary)' : 'var(--danger)' }}>
            {selected.cost.minerals} minerals · {selected.cost.fuel} fuel{selected.cost.currency ? ` · ${selected.cost.currency} currency` : ''}
          </span></div>
          <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 2 }}>
            Builds in {selected.buildTicks} tick{selected.buildTicks !== 1 ? 's' : ''} · {selected.buildTicks * 2}h
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, paddingBottom: 2 }}>
          <Btn variant="amber" onClick={handleBuild} disabled={submitting || !canAfford}>
            {submitting ? 'Queuing…' : 'Build'}
          </Btn>
        </div>
      </div>
      {error && <p style={{ color: 'var(--danger)', fontSize: 13, marginTop: 10 }}>{error}</p>}
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
  const [demolishing, setDemolishing] = useState(null)
  const [demolishError, setDemolishError] = useState('')
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

  const handleBuilt = () => load()

  const handleDemolish = async (facilityId) => {
    setDemolishing(facilityId)
    setDemolishError('')
    try {
      const r = await fetch(`/api/facilities/${facilityId}/demolish`, {
        method: 'POST',
        credentials: 'include',
      })
      const data = await r.json()
      if (!r.ok) { setDemolishError(data.detail || 'Demolish failed'); return }
      setFacilities(fs => fs.map(f => f.id === facilityId ? data : f))
    } catch {
      setDemolishError('Network error')
    } finally {
      setDemolishing(null)
    }
  }

  if (nationLoading || loading) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  const COLUMNS = [
    { key: 'type',      label: 'Type',      compare: (a, b) => (TYPE_LABEL[a.type] || a.type).localeCompare(TYPE_LABEL[b.type] || b.type) },
    { key: 'territory', label: 'Territory', compare: (a, b) => (a.territory_name || a.territory_node_key).localeCompare(b.territory_name || b.territory_node_key) },
    { key: 'status',    label: 'Status',    compare: (a, b) => a.status.localeCompare(b.status) },
    { key: 'completes', label: 'Completes', compare: (a, b) => (a.completes_at || '').localeCompare(b.completes_at || '') },
    { key: 'level',     label: 'Level',     compare: (a, b) => a.level - b.level },
    { key: 'actions',   label: '',          compare: () => 0 },
  ]

  const handleSort = key => {
    if (key === 'actions') return
    if (sortKey === key) setSortAsc(a => !a)
    else { setSortKey(key); setSortAsc(true) }
  }

  const sortedFacilities = sortKey
    ? [...facilities].sort((a, b) => {
        const col = COLUMNS.find(c => c.key === sortKey)
        return sortAsc ? col.compare(a, b) : col.compare(b, a)
      })
    : facilities

  const activeFacilities = facilities.filter(f => f.status === 'active').length
  const inProgress = facilities.filter(f => f.status !== 'active').length

  return (
    <div>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 22, fontWeight: 600 }}>Facilities</h1>
        <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
          All infrastructure across your empire
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 14, marginBottom: 28 }}>
        <StatCard label="Active Facilities" value={activeFacilities} />
        {inProgress > 0 && <StatCard label="In Progress" value={inProgress} accent="var(--amber)" />}
        <StatCard label="Minerals" value={nation ? parseFloat(nation.minerals).toFixed(0) : '—'} accent="var(--amber)" />
        <StatCard label="Fuel" value={nation ? parseFloat(nation.fuel).toFixed(0) : '—'} accent="var(--teal)" />
      </div>

      {territories.length > 0 && (
        <BuildForm territories={territories} nation={nation} onBuilt={handleBuilt} />
      )}

      <SectionLabel>All Facilities</SectionLabel>

      {error && <p style={{ color: 'var(--danger)' }}>{error}</p>}
      {demolishError && <p style={{ color: 'var(--danger)', fontSize: 13, marginBottom: 8 }}>{demolishError}</p>}

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
                        cursor: col.key !== 'actions' ? 'pointer' : 'default',
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
                    <Td><Badge color={f.type === 'mine' ? 'amber' : 'teal'}>{TYPE_LABEL[f.type] || f.type}</Badge></Td>
                    <Td>{f.territory_name || f.territory_node_key}</Td>
                    <Td><Badge color={statusBadgeColor(f.status)}>{statusLabel(f.status)}</Badge></Td>
                    <Td muted>{f.completes_at ? <CountdownCell isoTs={f.completes_at} /> : '—'}</Td>
                    <Td muted>{f.level}</Td>
                    <Td>
                      {f.status === 'active' && (
                        <Btn
                          variant="ghost"
                          onClick={() => handleDemolish(f.id)}
                          disabled={demolishing === f.id}
                          style={{ fontSize: 11, padding: '3px 10px', color: 'var(--danger)', borderColor: 'var(--danger)' }}
                        >
                          {demolishing === f.id ? 'Queuing…' : 'Demolish'}
                        </Btn>
                      )}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 10 }}>
        Demolishing returns 25% of build cost after 1 tick (2h). Only active facilities can be demolished.
      </p>
    </div>
  )
}
