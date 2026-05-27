import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNation } from '../hooks/useNation'
import { useDiplomacy } from '../hooks/useDiplomacy'
import { Card, SectionLabel, EmptyState, Table, Tr, Td, Btn, StatCard } from '../components/ui'

const HEX_SIZE = 9
const SVG_W = 800
const SVG_H = 640
const PROBE_RANGE = 10

function hexToSvg(q, r) {
  return [
    SVG_W / 2 + HEX_SIZE * (Math.sqrt(3) * q + (Math.sqrt(3) / 2) * r),
    SVG_H / 2 + HEX_SIZE * 1.5 * r,
  ]
}

function hexDistance(keyA, keyB) {
  const [q1, r1] = keyA.split(',').map(Number)
  const [q2, r2] = keyB.split(',').map(Number)
  const dq = q2 - q1, dr = r2 - r1
  return Math.max(Math.abs(dq), Math.abs(dr), Math.abs(dq + dr))
}

function fmtAgo(iso) {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const h = Math.floor(diff / 3600000)
  if (h < 1) return `${Math.floor(diff / 60000)}m ago`
  if (h < 24) return `${h}h ago`
  return new Date(iso).toLocaleDateString()
}

function fmtEta(isoArrives) {
  if (!isoArrives) return '—'
  const diff = new Date(isoArrives).getTime() - Date.now()
  if (diff <= 0) return 'Arriving'
  const h = Math.floor(diff / 3600000)
  const m = Math.floor((diff % 3600000) / 60000)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

function ManufactureForm({ stats, onManufactured, onCancel }) {
  const [quantity, setQuantity] = useState(1)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const mineralCost = stats.manufacture_cost_minerals * quantity
  const fuelCost = stats.manufacture_cost_fuel * quantity
  const currencyCost = stats.manufacture_cost_currency * quantity

  const handleBuild = async () => {
    setSubmitting(true)
    setError('')
    try {
      const r = await fetch('/api/probes/manufacture', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quantity }),
      })
      const data = await r.json()
      if (!r.ok) { setError(data.detail || 'Failed'); return }
      onManufactured(data)
    } catch {
      setError('Network error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card style={{ marginBottom: 24 }}>
      <div style={{ marginBottom: 12, fontWeight: 500 }}>
        Manufacture Probes
        <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 12 }}>
          {stats.nodes_per_tick} node{stats.nodes_per_tick !== 1 ? 's' : ''} per tick
        </span>
      </div>
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Quantity</div>
          <input
            type="number"
            min={1}
            value={quantity}
            onChange={e => setQuantity(Math.max(1, parseInt(e.target.value) || 1))}
            style={{ width: 80, padding: '6px 10px', background: 'var(--bg-base)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}
          />
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', paddingBottom: 2 }}>
          Cost: {mineralCost} minerals · {fuelCost} fuel · {currencyCost} currency
        </div>
        <div style={{ display: 'flex', gap: 8, paddingBottom: 2 }}>
          <Btn variant="amber" onClick={handleBuild} disabled={submitting}>{submitting ? 'Building…' : 'Manufacture'}</Btn>
          <Btn variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Btn>
        </div>
      </div>
      {error && <p style={{ color: 'var(--danger)', fontSize: 13, marginTop: 10 }}>{error}</p>}
    </Card>
  )
}

function LaunchMap({ territories, nationId, onLaunched, onCancel }) {
  const [origin, setOrigin] = useState(null)
  const [destination, setDestination] = useState(null)
  const [hovered, setHovered] = useState(null)
  const [launching, setLaunching] = useState(false)
  const [error, setError] = useState('')

  const ownedKeys = useMemo(
    () => territories.filter(t => t.nation_id === nationId && t.is_colonized).map(t => t.node_key),
    [territories, nationId]
  )

  const inRangeIds = useMemo(() => {
    const ids = new Set()
    for (const t of territories) {
      if (t.territory_type === 'void') continue
      const minDist = Math.min(...ownedKeys.map(ok => hexDistance(t.node_key, ok)))
      if (minDist <= PROBE_RANGE) ids.add(t.id)
    }
    return ids
  }, [territories, ownedKeys])

  const travelTicks = (origin && destination) ? hexDistance(origin.node_key, destination.node_key) : null

  const handleClick = (t) => {
    if (t.territory_type === 'void') return

    if (!origin) {
      if (t.nation_id === nationId && t.is_colonized) {
        setOrigin(t)
        setDestination(null)
        setError('')
      }
      return
    }

    if (t.id === origin.id) {
      setOrigin(null)
      setDestination(null)
      return
    }

    if (!inRangeIds.has(t.id)) return

    setDestination(t)
    setError('')
  }

  const handleLaunch = async () => {
    if (!origin || !destination) return
    setLaunching(true)
    setError('')
    try {
      const r = await fetch('/api/probes/dispatch', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_territory_id: origin.id, to_territory_id: destination.id }),
      })
      const data = await r.json()
      if (!r.ok) { setError(data.detail || 'Failed'); return }
      onLaunched()
    } catch {
      setError('Network error')
    } finally {
      setLaunching(false)
    }
  }

  const tooltip = hovered ? territories.find(t => t.id === hovered) : null

  return (
    <Card style={{ marginBottom: 24, padding: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ fontWeight: 500, fontSize: 14 }}>Launch Probe — Select Origin then Destination</div>
        <Btn variant="ghost" onClick={onCancel} style={{ fontSize: 12, padding: '3px 10px' }}>Cancel</Btn>
      </div>

      <div style={{ display: 'flex', gap: 16, marginBottom: 10, fontSize: 12, color: 'var(--text-secondary)', flexWrap: 'wrap' }}>
        {[
          { color: '#3ec9b4', label: 'Your territory (origin)' },
          { color: '#457b9d', label: 'In range' },
          { color: '#9268d4', label: 'Other nations' },
          { color: '#2a2f50', label: 'Out of range' },
        ].map(({ color, label }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block' }} />
            {label}
          </div>
        ))}
      </div>

      <svg
        width={SVG_W}
        height={SVG_H}
        style={{ background: '#07080f', borderRadius: 6, display: 'block', margin: '0 auto' }}
      >
        {territories.map(t => {
          const [q, r] = t.node_key.split(',').map(Number)
          const [x, y] = hexToSvg(q, r)
          const isOwn = t.nation_id === nationId
          const isOrigin = origin?.id === t.id
          const isDest = destination?.id === t.id
          const isVoid = t.territory_type === 'void'
          const inRange = inRangeIds.has(t.id)
          const isHovered = t.id === hovered

          let fill, opacity, cursor
          if (isVoid) {
            fill = '#1a1a2e'; opacity = 1; cursor = 'default'
          } else if (isOwn) {
            fill = '#3ec9b4'; opacity = 1; cursor = 'pointer'
          } else if (inRange) {
            fill = t.nation_id ? '#9268d4' : '#457b9d'; opacity = 1; cursor = 'pointer'
          } else {
            fill = '#2a2f50'; opacity = 0.4; cursor = 'default'
          }

          const baseR = isOrigin ? 6.5 : isDest ? 6 : isOwn ? 5 : isHovered ? 4.5 : 3.5
          const stroke = isOrigin ? '#fff' : isDest ? '#f59e0b' : 'none'
          const strokeW = isOrigin || isDest ? 2 : 0

          return (
            <circle
              key={t.id}
              cx={x} cy={y} r={baseR}
              fill={fill}
              stroke={stroke}
              strokeWidth={strokeW}
              opacity={opacity}
              style={{ cursor }}
              onClick={() => handleClick(t)}
              onMouseEnter={() => setHovered(t.id)}
              onMouseLeave={() => setHovered(null)}
            />
          )
        })}
      </svg>

      <div style={{ height: 20, marginTop: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
        {tooltip && !tooltip.territory_type === 'void' && (
          <>
            <strong style={{ color: 'var(--text-primary)' }}>{tooltip.node_key}</strong>
            {tooltip.nation_name && <> — <span style={{ color: tooltip.nation_id === nation?.id ? 'var(--teal)' : colorOf(tooltip.nation_id) }}>{tooltip.nation_name}</span></>}
          </>
        )}
      </div>

      {(origin || error) && (
        <div style={{ marginTop: 10, display: 'flex', gap: 24, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ fontSize: 13 }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 3 }}>From</div>
            {origin
              ? <span style={{ color: 'var(--teal)' }}>{origin.name || origin.node_key}</span>
              : <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>Click your territory</span>
            }
          </div>
          <div style={{ fontSize: 13 }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 3 }}>To</div>
            {destination
              ? <span style={{ color: 'var(--amber)' }}>{destination.name || destination.node_key}</span>
              : <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>Click a destination</span>
            }
            {travelTicks !== null && (
              <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 2 }}>
                {travelTicks} tick{travelTicks !== 1 ? 's' : ''} · {travelTicks * 2}h travel time
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn
              variant="primary"
              onClick={handleLaunch}
              disabled={!origin || !destination || launching}
            >
              {launching ? 'Launching…' : 'Launch'}
            </Btn>
          </div>
          {error && <p style={{ color: 'var(--danger)', fontSize: 13, margin: 0 }}>{error}</p>}
        </div>
      )}
    </Card>
  )
}

export default function Probes() {
  const { nation } = useNation()
  const { colorOf } = useDiplomacy()
  const [stats, setStats] = useState(null)
  const [nationData, setNationData] = useState(null)
  const [activeProbes, setActiveProbes] = useState([])
  const [probeData, setProbeData] = useState([])
  const [territories, setTerritories] = useState([])
  const [loading, setLoading] = useState(true)
  const [showManufacture, setShowManufacture] = useState(false)
  const [showLaunch, setShowLaunch] = useState(false)

  const load = useCallback(async () => {
    try {
      const [sRes, nRes, apRes, pdRes, tRes] = await Promise.all([
        fetch('/api/probes/stats', { credentials: 'include' }),
        fetch('/api/nations/mine', { credentials: 'include' }),
        fetch('/api/probes/active', { credentials: 'include' }),
        fetch('/api/probes/data', { credentials: 'include' }),
        fetch('/api/territories', { credentials: 'include' }),
      ])
      const [s, n, ap, pd, t] = await Promise.all([
        sRes.json(), nRes.json(), apRes.json(), pdRes.json(), tRes.json(),
      ])
      setStats(s)
      setNationData(n)
      setActiveProbes(Array.isArray(ap) ? ap : [])
      setProbeData(Array.isArray(pd) ? pd : [])
      setTerritories(Array.isArray(t) ? t : [])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleManufactured = updatedNation => {
    setNationData(updatedNation)
    setShowManufacture(false)
    load()
  }

  const handleLaunched = () => {
    setShowLaunch(false)
    load()
  }

  if (loading) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600 }}>Probes</h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
            Active probes, discovered system data, and the information marketplace
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          {!showManufacture && (
            <Btn variant="ghost" onClick={() => setShowManufacture(true)}>Manufacture Probes</Btn>
          )}
          {!showLaunch && (
            <Btn variant="primary" onClick={() => { setShowLaunch(true); setShowManufacture(false) }}>Launch Probe</Btn>
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 14, marginBottom: 28 }}>
        <StatCard label="Probes in Reserve" value={stats?.reserve ?? '—'} accent="var(--teal)" />
        <StatCard label="Minerals" value={nationData ? parseFloat(nationData.minerals).toFixed(0) : '—'} accent="var(--amber)" />
        <StatCard label="Fuel" value={nationData ? parseFloat(nationData.fuel).toFixed(0) : '—'} accent="var(--teal)" />
      </div>

      {showManufacture && stats && (
        <ManufactureForm
          stats={stats}
          onManufactured={handleManufactured}
          onCancel={() => setShowManufacture(false)}
        />
      )}

      {showLaunch && (
        <LaunchMap
          territories={territories}
          nationId={nation?.id}
          onLaunched={handleLaunched}
          onCancel={() => setShowLaunch(false)}
        />
      )}

      <SectionLabel>Active Probes</SectionLabel>
      <Card style={{ padding: 0 }}>
        {activeProbes.length === 0 ? (
          <Table headers={['Probe #', 'From', 'Current', 'Destination', 'ETA', 'Status']}>
            <Tr>
              <Td colSpan={6} style={{ textAlign: 'center', padding: '40px 0' }}>
                <EmptyState title="No active probes" body="Launch probes from colonized territories to scout uncharted systems." />
              </Td>
            </Tr>
          </Table>
        ) : (
          <Table headers={['Probe #', 'From', 'Current', 'Destination', 'ETA', 'Status']}>
            {activeProbes.map(p => (
              <Tr key={p.id}>
                <Td muted>#{p.id}</Td>
                <Td>{p.origin_name || p.origin_node_key || '—'}</Td>
                <Td>{p.current_node_key || '—'}</Td>
                <Td>{p.destination_name || p.destination_node_key || '—'}</Td>
                <Td muted>{p.status === 'in_transit' ? fmtEta(p.arrives_at) : '—'}</Td>
                <Td accent={p.status === 'stationed' ? 'teal' : undefined} muted={p.status !== 'stationed'}>
                  {p.status === 'in_transit' ? 'In Transit' : 'Stationed'}
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <SectionLabel>Your Intelligence</SectionLabel>
      <Card style={{ padding: 0 }}>
        {probeData.length === 0 ? (
          <Table headers={['Planet', 'Coordinates', 'Minerals', 'Fuel', 'Scouted', 'Status']}>
            <Tr>
              <Td colSpan={6} style={{ textAlign: 'center', padding: '40px 0' }}>
                <EmptyState title="No probe data yet" body="Data collected by your probes will appear here." />
              </Td>
            </Tr>
          </Table>
        ) : (
          <Table headers={['Planet', 'Coordinates', 'Minerals', 'Fuel', 'Scouted', 'Status']}>
            {probeData.map(pd => (
              <Tr key={pd.id}>
                <Td>
                  {pd.territory_name
                    ? pd.territory_name
                    : <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>Unnamed</span>
                  }
                </Td>
                <Td muted style={{ fontFamily: 'monospace', fontSize: 12 }}>{pd.node_key}</Td>
                <Td muted>{Number(pd.mineral_richness).toFixed(2)}</Td>
                <Td muted>{Number(pd.fuel_richness).toFixed(2)}</Td>
                <Td muted>{fmtAgo(pd.discovered_at)}</Td>
                <Td>
                  {pd.is_colonized
                    ? <span style={{ color: pd.nation_id === nation?.id ? 'var(--teal)' : colorOf(pd.nation_id) }}>Colonized{pd.nation_name ? ` by ${pd.nation_name}` : ''}</span>
                    : <span style={{ color: 'var(--text-muted)' }}>Unclaimed</span>
                  }
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  )
}
