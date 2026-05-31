import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNation } from '../hooks/useNation'
import { useDiplomacy } from '../hooks/useDiplomacy'
import { PageHeader, Card, Btn } from '../components/ui'

const HEX_SIZE = 9
const SVG_W = 800
const SVG_H = 640
// Set to a number to cap fleet dispatch range; null = unlimited
const FLEET_MAX_RANGE = null

function hexToSvg(q, r) {
  return [
    SVG_W / 2 + HEX_SIZE * (Math.sqrt(3) * q + (Math.sqrt(3) / 2) * r),
    SVG_H / 2 + HEX_SIZE * 1.5 * r,
  ]
}

function territoryColor(t, myNationId) {
  if (t.nation_id === myNationId) return '#3ec9b4'
  if (t.nation_id) return '#9268d4'
  if (t.distance_from_center <= 2)  return '#e8943a'
  if (t.distance_from_center <= 6)  return '#457b9d'
  if (t.distance_from_center <= 10) return '#52796f'
  return '#2a2f50'
}

function hexDistance(keyA, keyB) {
  const [q1, r1] = keyA.split(',').map(Number)
  const [q2, r2] = keyB.split(',').map(Number)
  const dq = q2 - q1, dr = r2 - r1
  return Math.max(Math.abs(dq), Math.abs(dr), Math.abs(dq + dr))
}

export default function MapView() {
  const { nation } = useNation()
  const { colorOf } = useDiplomacy()
  const [territories, setTerritories] = useState([])
  const [fleets, setFleets] = useState([])
  const [wars, setWars] = useState([])
  const [loading, setLoading] = useState(true)
  const [hovered, setHovered] = useState(null)

  // Fleet send state
  const [source, setSource] = useState(null)     // territory object
  const [dest, setDest] = useState(null)          // territory object
  const [sendQty, setSendQty] = useState(1)
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState('')
  const [sendSuccess, setSendSuccess] = useState('')

  // Nation info panel (enemy territory click)
  const [nationPanel, setNationPanel] = useState(null)  // { nationId, nationName, territory }
  const [declaringWar, setDeclaringWar] = useState(false)
  const [warError, setWarError] = useState('')

  const load = useCallback(async () => {
    const [tRes, fRes, wRes] = await Promise.all([
      fetch('/api/territories', { credentials: 'include' }),
      fetch('/api/military/fleets', { credentials: 'include' }),
      fetch('/api/diplomacy/wars', { credentials: 'include' }),
    ])
    const [t, f, w] = await Promise.all([
      tRes.ok ? tRes.json() : [],
      fRes.ok ? fRes.json() : [],
      wRes.ok ? wRes.json() : [],
    ])
    setTerritories(t)
    setFleets(f)
    setWars(w)
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  // Map territory_id → stationed fighter count
  const stationedByTerritory = {}
  for (const f of fleets) {
    if (f.status === 'stationed' && f.origin_territory_id) {
      stationedByTerritory[f.origin_territory_id] = (stationedByTerritory[f.origin_territory_id] || 0) + f.unit_count
    }
  }

  const sourceFleet = source
    ? fleets.find(f => f.status === 'stationed' && f.origin_territory_id === source.id)
    : null
  const maxQty = sourceFleet?.unit_count ?? 0

  const travelTicks = (source && dest)
    ? Math.ceil(hexDistance(source.node_key, dest.node_key) / 2)
    : null

  // IDs of territories reachable from the selected source (null when not in deploy mode)
  const reachableIds = useMemo(() => {
    if (!source) return null
    const ids = new Set()
    for (const t of territories) {
      if (t.territory_type === 'void') continue
      if (!FLEET_MAX_RANGE || hexDistance(source.node_key, t.node_key) <= FLEET_MAX_RANGE) {
        ids.add(t.id)
      }
    }
    return ids
  }, [source, territories])

  const handleDeclareWar = async () => {
    if (!nationPanel) return
    setDeclaringWar(true)
    setWarError('')
    try {
      const r = await fetch('/api/diplomacy/war', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_nation_id: nationPanel.nationId }),
      })
      const data = await r.json()
      if (!r.ok) { setWarError(data.detail || 'Failed'); return }
      load()
    } catch {
      setWarError('Network error')
    } finally {
      setDeclaringWar(false)
    }
  }

  const handleTerritoryClick = (t) => {
    if (t.territory_type === 'void') return
    setSendError('')
    setSendSuccess('')

    // Clicking an enemy territory — show nation info panel (or set as fleet dest if deploying)
    if (t.nation_id && t.nation_id !== nation?.id) {
      if (source) {
        // In fleet-send mode: set as destination
        setDest(t)
        setSendQty(Math.min(sendQty, maxQty))
        setNationPanel(null)
      } else {
        // Show nation panel
        setNationPanel({ nationId: t.nation_id, nationName: t.nation_name, territory: t })
        setWarError('')
      }
      return
    }

    setNationPanel(null)

    // If no source yet and this is our territory with stationed fighters — select as source
    if (!source) {
      if (t.nation_id === nation?.id && stationedByTerritory[t.id] > 0) {
        setSource(t)
        setDest(null)
        setSendQty(stationedByTerritory[t.id])  // default: move entire fleet
      }
      return
    }

    // If clicking source again — deselect
    if (source.id === t.id) {
      setSource(null)
      setDest(null)
      return
    }

    // Block out-of-range destinations
    if (reachableIds && !reachableIds.has(t.id)) return

    // Otherwise select as destination
    setDest(t)
    setSendQty(Math.min(sendQty, maxQty))
  }

  const handleSend = async () => {
    if (!source || !dest || sendQty < 1) return
    setSending(true)
    setSendError('')
    setSendSuccess('')
    try {
      const r = await fetch('/api/military/fleets/send', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from_territory_id: source.id,
          to_territory_id: dest.id,
          quantity: sendQty,
        }),
      })
      const data = await r.json()
      if (!r.ok) { setSendError(data.detail || 'Failed'); return }
      setSendSuccess(`Fleet of ${sendQty} dispatched — arrives in ${travelTicks} tick${travelTicks !== 1 ? 's' : ''}.`)
      setSource(null)
      setDest(null)
      load()
    } catch {
      setSendError('Network error')
    } finally {
      setSending(false)
    }
  }

  const tooltip = hovered ? territories.find(t => t.id === hovered) : null

  return (
    <div>
      <PageHeader
        title="Map"
        sub="The shared galaxy — click your territory to deploy fighters"
      />

      {/* Legend */}
      <div style={{ display: 'flex', gap: 20, marginBottom: 16, fontSize: 12, color: 'var(--text-secondary)', flexWrap: 'wrap' }}>
        {[
          { color: '#3ec9b4', label: 'Your territory' },
          { color: '#9268d4', label: 'Other nations' },
          { color: '#e8943a', label: 'Unclaimed core' },
          { color: '#457b9d', label: 'Unclaimed mid' },
          { color: '#52796f', label: 'Unclaimed mid-rim' },
          { color: '#2a2f50', label: 'Rim' },
        ].map(({ color, label }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block' }} />
            {label}
          </div>
        ))}
      </div>

      <Card style={{ padding: 12 }}>
        {loading ? (
          <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 40 }}>Loading map&hellip;</p>
        ) : territories.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 40 }}>
            No territory data. Run the seeder: <code>docker compose exec backend python -m app.seed</code>
          </p>
        ) : (
          <svg
            width={SVG_W}
            height={SVG_H}
            style={{ background: '#07080f', borderRadius: 6, display: 'block', margin: '0 auto' }}
          >
            {territories.map(t => {
              const [q, r] = t.node_key.split(',').map(Number)
              const [x, y] = hexToSvg(q, r)
              const isMyTerritory = t.nation_id === nation?.id
              const isSource = source?.id === t.id
              const isDest = dest?.id === t.id
              const isHovered = t.id === hovered
              const hasfighters = stationedByTerritory[t.id] > 0
              const isDeployMode = !!source
              const isReachable = !isDeployMode || (reachableIds?.has(t.id) ?? true)
              const fill = territoryColor(t, nation?.id)
              const baseR = isSource ? 6.5 : isDest ? 6 : isMyTerritory ? 5 : isHovered ? 4.5 : 3.5
              const stroke = isSource ? '#fff' : isDest ? '#f59e0b' : hasfighters && isMyTerritory ? '#3ec9b4' : isHovered ? '#aaa' : 'none'
              const strokeW = isSource || isDest ? 2 : 1
              const opacity = !isReachable ? 0.15 : (isHovered || isMyTerritory || isSource || isDest ? 1 : 0.75)

              return (
                <g key={t.id}>
                  <circle
                    cx={x} cy={y} r={baseR}
                    fill={fill}
                    stroke={stroke}
                    strokeWidth={strokeW}
                    opacity={opacity}
                    style={{ cursor: t.territory_type === 'void' || (isDeployMode && !isReachable) ? 'default' : 'pointer' }}
                    onClick={() => handleTerritoryClick(t)}
                    onMouseEnter={() => setHovered(t.id)}
                    onMouseLeave={() => setHovered(null)}
                  />
                  {/* Fighter count dot for territories with stationed units */}
                  {hasfighters && isMyTerritory && (
                    <circle cx={x + baseR - 1} cy={y - baseR + 1} r={2.5} fill="#f59e0b" style={{ pointerEvents: 'none' }} />
                  )}
                </g>
              )
            })}
          </svg>
        )}
      </Card>

      {/* Hover tooltip */}
      <div style={{ height: 24, marginTop: 8, fontSize: 13, color: 'var(--text-secondary)' }}>
        {tooltip && (
          <>
            <strong style={{ color: 'var(--text-primary)' }}>{tooltip.node_key}</strong>
            {' — '}
            {tooltip.nation_name
              ? <span style={{ color: tooltip.nation_id === nation?.id ? 'var(--teal)' : colorOf(tooltip.nation_id) }}>{tooltip.nation_name}</span>
              : <span style={{ color: 'var(--text-muted)' }}>Unclaimed</span>
            }
            {' · '}Distance {tooltip.distance_from_center}
            {tooltip.mineral_richness != null && (
              <> &nbsp; Min {Number(tooltip.mineral_richness).toFixed(2)} &nbsp; Fuel {Number(tooltip.fuel_richness).toFixed(2)}</>
            )}
            {stationedByTerritory[tooltip.id] > 0 && (
              <> &nbsp; <span style={{ color: '#f59e0b' }}>⚔ {stationedByTerritory[tooltip.id]} fighters</span></>
            )}
          </>
        )}
      </div>

      {/* Deploy Fleet panel */}
      {(source || sendSuccess) && (
        <Card style={{ marginTop: 16 }}>
          {sendSuccess ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--teal)', fontSize: 13 }}>{sendSuccess}</span>
              <Btn variant="ghost" onClick={() => setSendSuccess('')} style={{ fontSize: 12, padding: '3px 10px' }}>Dismiss</Btn>
            </div>
          ) : (
            <>
              <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 12 }}>Deploy Fleet</div>
              <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: 13 }}>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>From</div>
                  <div style={{ color: 'var(--teal)' }}>{source.name || source.node_key}</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 2 }}>{maxQty} fighters available</div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>To</div>
                  {dest
                    ? <div style={{ color: 'var(--amber)' }}>{dest.name || dest.node_key}</div>
                    : <div style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>Click a destination on the map</div>
                  }
                  {travelTicks !== null && (
                    <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 2 }}>
                      {travelTicks} tick{travelTicks !== 1 ? 's' : ''} · {travelTicks * 2}h travel time
                    </div>
                  )}
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>
                    Send
                    {sendQty < maxQty && (
                      <span style={{ color: 'var(--amber)', marginLeft: 6, textTransform: 'none', letterSpacing: 0 }}>
                        — splits fleet
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <input
                      type="number"
                      min={1}
                      max={maxQty}
                      value={sendQty}
                      onChange={e => setSendQty(Math.max(1, Math.min(maxQty, parseInt(e.target.value) || 1)))}
                      style={{ width: 70, padding: '5px 8px', background: 'var(--bg-base)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', fontSize: 13 }}
                    />
                    {sendQty < maxQty && (
                      <button
                        onClick={() => setSendQty(maxQty)}
                        style={{ fontSize: 11, color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 4px' }}
                        title="Send all"
                      >
                        All
                      </button>
                    )}
                  </div>
                  {sendQty < maxQty && (
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>
                      {maxQty - sendQty} remain behind
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8 }}>
                  <Btn
                    variant="amber"
                    onClick={handleSend}
                    disabled={!dest || sending || sendQty < 1}
                  >
                    {sending ? 'Sending…' : 'Send Fleet'}
                  </Btn>
                  <Btn variant="ghost" onClick={() => { setSource(null); setDest(null); setSendError('') }}>Cancel</Btn>
                </div>
              </div>
              {sendError && <p style={{ color: 'var(--danger)', fontSize: 13, marginTop: 10 }}>{sendError}</p>}
            </>
          )}
        </Card>
      )}

      {/* Nation info panel — shown when clicking an enemy territory */}
      {nationPanel && !source && (
        <Card style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: colorOf(nationPanel.nationId), marginBottom: 4 }}>
                {nationPanel.nationName}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                Territory: {nationPanel.territory.name || nationPanel.territory.node_key}
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
              {wars.some(w => w.nation_id === nationPanel.nationId) ? (
                <span style={{
                  fontSize: 12, fontWeight: 600, color: 'var(--danger)',
                  border: '1px solid var(--danger)', borderRadius: 4, padding: '3px 10px',
                }}>
                  AT WAR
                </span>
              ) : (
                <Btn
                  variant="danger"
                  disabled={declaringWar}
                  onClick={handleDeclareWar}
                  style={{ fontSize: 12, padding: '4px 12px' }}
                >
                  {declaringWar ? 'Declaring…' : 'Declare War'}
                </Btn>
              )}
              <Btn variant="ghost" onClick={() => { setNationPanel(null); setWarError('') }}
                style={{ fontSize: 12, padding: '4px 10px' }}>
                ✕
              </Btn>
            </div>
          </div>
          {warError && (
            <div style={{ marginTop: 8, fontSize: 12, color: 'var(--danger)' }}>{warError}</div>
          )}
        </Card>
      )}

      {/* Instruction hint */}
      {!source && !sendSuccess && !nationPanel && (
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 10 }}>
          Click one of your territories (amber dot = fighters stationed) to deploy a fleet.
          Click an enemy territory to view their nation.
        </p>
      )}
    </div>
  )
}
