import { useState, useEffect, useCallback } from 'react'
import { Card, SectionLabel, EmptyState, Table, Tr, Td, Badge, Btn, StatCard } from '../components/ui'

const UNIT_LABELS = { starfighter: 'Starfighter' }
const SELECT_STYLE = { padding: '6px 10px', background: 'var(--bg-base)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }
const INPUT_STYLE = { width: 80, padding: '6px 10px', background: 'var(--bg-base)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }

function ManufactureForm({ unit, shipyardTerritories, onManufactured, onCancel }) {
  const [quantity, setQuantity] = useState(1)
  const [territoryId, setTerritoryId] = useState(shipyardTerritories[0]?.id ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const mineralCost = unit.manufacture_cost_minerals * quantity
  const fuelCost = unit.manufacture_cost_fuel * quantity
  const currencyCost = unit.manufacture_cost_currency * quantity

  const handleBuild = async () => {
    if (!territoryId) { setError('Select a territory'); return }
    setSubmitting(true)
    setError('')
    try {
      const r = await fetch(`/api/military/manufacture/${unit.type}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quantity, territory_id: Number(territoryId) }),
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
        Manufacture {UNIT_LABELS[unit.type] || unit.type}
        <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 12 }}>
          ATK {unit.attack} · Shields {unit.shields} · Str. Int. {unit.structural_integrity}
        </span>
      </div>
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Build at</div>
          <select value={territoryId} onChange={e => setTerritoryId(e.target.value)} style={SELECT_STYLE}>
            {shipyardTerritories.map(t => (
              <option key={t.id} value={t.id}>{t.territory_name || t.territory_node_key}</option>
            ))}
          </select>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Quantity</div>
          <input type="number" min={1} value={quantity} onChange={e => setQuantity(Math.max(1, parseInt(e.target.value) || 1))} style={INPUT_STYLE} />
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

function BuildColonyShipForm({ shipyardTerritories, onBuilt, onCancel }) {
  const [territoryId, setTerritoryId] = useState(shipyardTerritories[0]?.id ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleBuild = async () => {
    if (!territoryId) { setError('Select a territory'); return }
    setSubmitting(true)
    setError('')
    try {
      const r = await fetch('/api/military/manufacture/colony-ship', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ territory_id: Number(territoryId) }),
      })
      const data = await r.json()
      if (!r.ok) { setError(data.detail || 'Failed'); return }
      onBuilt(data)
    } catch {
      setError('Network error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card style={{ marginBottom: 24 }}>
      <div style={{ marginBottom: 12, fontWeight: 500 }}>Build Colony Ship
        <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 12 }}>500 minerals · 1000 fuel · 1 node/tick · 100 pop capacity</span>
      </div>
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Build at</div>
          <select value={territoryId} onChange={e => setTerritoryId(e.target.value)} style={SELECT_STYLE}>
            {shipyardTerritories.map(t => (
              <option key={t.id} value={t.id}>{t.territory_name || t.territory_node_key}</option>
            ))}
          </select>
        </div>
        <div style={{ display: 'flex', gap: 8, paddingBottom: 2 }}>
          <Btn variant="amber" onClick={handleBuild} disabled={submitting}>{submitting ? 'Building…' : 'Build'}</Btn>
          <Btn variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Btn>
        </div>
      </div>
      {error && <p style={{ color: 'var(--danger)', fontSize: 13, marginTop: 10 }}>{error}</p>}
    </Card>
  )
}

function ColonyShipActions({ ship, ownedTerritories, onAction }) {
  const [panel, setPanel] = useState(null) // 'load' | 'unload' | 'send'
  const [quantity, setQuantity] = useState(1)
  const [destId, setDestId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const openPanel = p => { setPanel(panel === p ? null : p); setError(''); setQuantity(1) }

  const handleCargo = async (action) => {
    setSubmitting(true)
    setError('')
    try {
      const r = await fetch(`/api/military/colony-ships/${ship.id}/${action}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quantity }),
      })
      const data = await r.json()
      if (!r.ok) { setError(data.detail || 'Failed'); return }
      setPanel(null)
      onAction()
    } catch {
      setError('Network error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleSend = async () => {
    if (!destId) { setError('Select a destination'); return }
    setSubmitting(true)
    setError('')
    try {
      const r = await fetch(`/api/military/colony-ships/${ship.id}/send`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to_territory_id: Number(destId) }),
      })
      const data = await r.json()
      if (!r.ok) { setError(data.detail || 'Failed'); return }
      setPanel(null)
      onAction()
    } catch {
      setError('Network error')
    } finally {
      setSubmitting(false)
    }
  }

  const maxLoad = Math.min(100 - ship.cargo_population, ship.origin_current_population ?? 0)
  const destinations = ownedTerritories.filter(t => t.id !== ship.origin_territory_id && t.is_colonized)

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <Btn variant="ghost" onClick={() => openPanel('load')} style={{ padding: '3px 10px', fontSize: 12 }} disabled={maxLoad <= 0}>Load</Btn>
        <Btn variant="ghost" onClick={() => openPanel('unload')} style={{ padding: '3px 10px', fontSize: 12 }} disabled={ship.cargo_population <= 0}>Unload</Btn>
        <Btn variant="ghost" onClick={() => { openPanel('send'); setDestId(destinations[0]?.id ?? '') }} style={{ padding: '3px 10px', fontSize: 12 }}>Deploy</Btn>
      </div>
      {panel === 'load' && (
        <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Load (max {maxLoad})</span>
          <input type="number" min={1} max={maxLoad} value={quantity} onChange={e => setQuantity(Math.max(1, Math.min(maxLoad, parseInt(e.target.value) || 1)))} style={{ ...INPUT_STYLE, width: 60 }} />
          <Btn variant="amber" onClick={() => handleCargo('load')} disabled={submitting} style={{ padding: '3px 10px', fontSize: 12 }}>{submitting ? '…' : 'Confirm'}</Btn>
          <Btn variant="ghost" onClick={() => setPanel(null)} disabled={submitting} style={{ padding: '3px 10px', fontSize: 12 }}>Cancel</Btn>
        </div>
      )}
      {panel === 'unload' && (
        <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Unload (max {ship.cargo_population})</span>
          <input type="number" min={1} max={ship.cargo_population} value={quantity} onChange={e => setQuantity(Math.max(1, Math.min(ship.cargo_population, parseInt(e.target.value) || 1)))} style={{ ...INPUT_STYLE, width: 60 }} />
          <Btn variant="amber" onClick={() => handleCargo('unload')} disabled={submitting} style={{ padding: '3px 10px', fontSize: 12 }}>{submitting ? '…' : 'Confirm'}</Btn>
          <Btn variant="ghost" onClick={() => setPanel(null)} disabled={submitting} style={{ padding: '3px 10px', fontSize: 12 }}>Cancel</Btn>
        </div>
      )}
      {panel === 'send' && (
        <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <select value={destId} onChange={e => setDestId(e.target.value)} style={SELECT_STYLE}>
            {destinations.length === 0
              ? <option value="">No other territories</option>
              : destinations.map(t => <option key={t.id} value={t.id}>{t.name || t.node_key}</option>)
            }
          </select>
          <Btn variant="amber" onClick={handleSend} disabled={submitting || destinations.length === 0} style={{ padding: '3px 10px', fontSize: 12 }}>{submitting ? '…' : 'Send'}</Btn>
          <Btn variant="ghost" onClick={() => setPanel(null)} disabled={submitting} style={{ padding: '3px 10px', fontSize: 12 }}>Cancel</Btn>
        </div>
      )}
      {error && <p style={{ color: 'var(--danger)', fontSize: 12, marginTop: 6 }}>{error}</p>}
    </div>
  )
}

export default function Military() {
  const [units, setUnits] = useState([])
  const [fleets, setFleets] = useState([])
  const [colonyShips, setColonyShips] = useState([])
  const [ownedTerritories, setOwnedTerritories] = useState([])
  const [facilities, setFacilities] = useState([])
  const [nation, setNation] = useState(null)
  const [loading, setLoading] = useState(true)
  const [manufacturingUnit, setManufacturingUnit] = useState(null)
  const [buildingColonyShip, setBuildingColonyShip] = useState(false)
  const [claimingFleetId, setClaimingFleetId] = useState(null)
  const [claimError, setClaimError] = useState('')
  const [fleetActionPending, setFleetActionPending] = useState({})
  const [fleetActionErrors, setFleetActionErrors] = useState({})

  const load = useCallback(async () => {
    try {
      const [uRes, nRes, fRes, facRes, csRes, tRes] = await Promise.all([
        fetch('/api/military/units', { credentials: 'include' }),
        fetch('/api/nations/mine', { credentials: 'include' }),
        fetch('/api/military/fleets', { credentials: 'include' }),
        fetch('/api/facilities', { credentials: 'include' }),
        fetch('/api/military/colony-ships', { credentials: 'include' }),
        fetch('/api/nations/mine/territories', { credentials: 'include' }),
      ])
      const [u, n, f, fac, cs, t] = await Promise.all([
        uRes.json(), nRes.json(), fRes.json(), facRes.json(), csRes.json(), tRes.json(),
      ])
      setUnits(u)
      setNation(n)
      setFleets(f)
      setFacilities(fac)
      setColonyShips(cs)
      setOwnedTerritories(t)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleManufactured = () => { setManufacturingUnit(null); load() }
  const handleColonyShipBuilt = () => { setBuildingColonyShip(false); load() }

  const handleClaim = async (fleetId) => {
    setClaimingFleetId(fleetId)
    setClaimError('')
    try {
      const r = await fetch(`/api/military/fleets/${fleetId}/claim`, {
        method: 'POST',
        credentials: 'include',
      })
      const data = await r.json()
      if (!r.ok) { setClaimError(data.detail || 'Failed to claim territory'); return }
      load()
    } catch {
      setClaimError('Network error')
    } finally {
      setClaimingFleetId(null)
    }
  }

  const handleFleetAction = async (fleetId, action) => {
    setFleetActionErrors(prev => ({ ...prev, [fleetId]: '' }))
    setFleetActionPending(prev => ({ ...prev, [fleetId]: action }))
    try {
      const r = await fetch(`/api/military/fleets/${fleetId}/${action}`, {
        method: 'POST',
        credentials: 'include',
      })
      const data = await r.json()
      if (!r.ok) {
        setFleetActionErrors(prev => ({ ...prev, [fleetId]: data.detail || 'Failed' }))
        return
      }
      load()
    } catch {
      setFleetActionErrors(prev => ({ ...prev, [fleetId]: 'Network error' }))
    } finally {
      setFleetActionPending(prev => ({ ...prev, [fleetId]: null }))
    }
  }

  if (loading) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  const stationedFleets = fleets.filter(f => f.status === 'stationed')
  const transitFleets = fleets.filter(f => f.status === 'in_transit')
  const activeOpFleets = fleets.filter(f => ['pending_confirmation', 'engaged', 'holding'].includes(f.status))
  const totalUnits = fleets.reduce((s, f) => s + f.unit_count, 0)
  const stationedColonyShips = colonyShips.filter(s => s.status === 'stationed')
  const transitColonyShips = colonyShips.filter(s => s.status === 'in_transit')
  const shipyardTerritories = facilities.filter(f => f.type === 'shipyard')

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600 }}>Military</h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
            Fleet management, confirmation windows, and active wars
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <Btn variant="ghost" disabled>Declare War</Btn>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 14, marginBottom: 28 }}>
        <StatCard label="Total Fighters" value={totalUnits} />
        <StatCard label="Stationed" value={stationedFleets.reduce((s, f) => s + f.unit_count, 0)} accent="var(--teal)" />
        <StatCard label="In Transit" value={transitFleets.reduce((s, f) => s + f.unit_count, 0)} accent="var(--amber)" />
        <StatCard label="Colony Ships" value={colonyShips.length} accent="var(--teal)" />
        <StatCard label="Minerals" value={nation ? parseFloat(nation.minerals).toFixed(0) : '—'} accent="var(--amber)" />
        <StatCard label="Fuel" value={nation ? parseFloat(nation.fuel).toFixed(0) : '—'} accent="var(--teal)" />
      </div>

      <SectionLabel>Starfighters</SectionLabel>

      {manufacturingUnit && (
        <ManufactureForm
          unit={manufacturingUnit}
          shipyardTerritories={shipyardTerritories}
          onManufactured={handleManufactured}
          onCancel={() => setManufacturingUnit(null)}
        />
      )}

      <Card style={{ padding: 0, marginBottom: 28 }}>
        {units.length === 0 ? (
          <EmptyState title="No unit types available" body="Build a shipyard to unlock starfighters." />
        ) : (
          <Table headers={['Unit', 'ATK', 'Shields', 'Str. Int.', 'Speed', 'Manufacture Cost', '']}>
            {units.map(u => (
              <Tr key={u.type}>
                <Td><Badge color="rose">{UNIT_LABELS[u.type] || u.type}</Badge></Td>
                <Td>{u.attack}</Td>
                <Td>{u.shields}</Td>
                <Td>{u.structural_integrity}</Td>
                <Td muted>{u.nodes_per_tick} node{u.nodes_per_tick !== 1 ? 's' : ''}/tick</Td>
                <Td muted>{u.manufacture_cost_minerals}M / {u.manufacture_cost_fuel}F / {u.manufacture_cost_currency}¤</Td>
                <Td>
                  {shipyardTerritories.length > 0 ? (
                    <Btn
                      variant="ghost"
                      onClick={() => setManufacturingUnit(manufacturingUnit?.type === u.type ? null : u)}
                      style={{ padding: '3px 10px', fontSize: 12 }}
                    >
                      Manufacture
                    </Btn>
                  ) : (
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>No shipyard</span>
                  )}
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <SectionLabel>Stationed Fleets</SectionLabel>
      {claimError && <p style={{ color: 'var(--danger)', fontSize: 13, marginBottom: 10 }}>{claimError}</p>}
      <Card style={{ padding: 0, marginBottom: 28 }}>
        {stationedFleets.length === 0 ? (
          <EmptyState title="No stationed fighters" body="Manufacture starfighters at a shipyard. Use the map to deploy them." />
        ) : (
          <Table headers={['Territory', 'Fighters', 'Actions']}>
            {stationedFleets.map(f => (
              <Tr key={f.id}>
                <Td>
                  {f.origin_name || f.origin_node_key}
                  {f.origin_is_colonized === false && (
                    <Badge color="amber" style={{ marginLeft: 8 }}>Unclaimed</Badge>
                  )}
                </Td>
                <Td accent="teal">{f.unit_count}</Td>
                <Td>
                  {f.origin_is_colonized === false ? (
                    <Btn
                      variant="amber"
                      onClick={() => handleClaim(f.id)}
                      disabled={claimingFleetId === f.id}
                      style={{ padding: '3px 10px', fontSize: 12 }}
                    >
                      {claimingFleetId === f.id ? 'Claiming…' : 'Claim Territory'}
                    </Btn>
                  ) : (
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Use the Map to deploy</span>
                  )}
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <SectionLabel>In Transit</SectionLabel>
      <Card style={{ padding: 0, marginBottom: 28 }}>
        {transitFleets.length === 0 ? (
          <EmptyState title="No fleets in transit" />
        ) : (
          <Table headers={['Fighters', 'From', 'To', 'Arrives']}>
            {transitFleets.map(f => (
              <Tr key={f.id}>
                <Td accent="amber">{f.unit_count}</Td>
                <Td muted>{f.origin_name || f.origin_node_key}</Td>
                <Td>{f.destination_name || f.destination_node_key}</Td>
                <Td muted>{f.arrives_at ? new Date(f.arrives_at).toLocaleString() : '—'}</Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <SectionLabel>Colony Ships</SectionLabel>

      {buildingColonyShip && shipyardTerritories.length > 0 && (
        <BuildColonyShipForm
          shipyardTerritories={shipyardTerritories}
          onBuilt={handleColonyShipBuilt}
          onCancel={() => setBuildingColonyShip(false)}
        />
      )}

      {!buildingColonyShip && (
        <div style={{ marginBottom: 16 }}>
          {shipyardTerritories.length > 0 ? (
            <Btn variant="ghost" onClick={() => setBuildingColonyShip(true)} style={{ fontSize: 13 }}>Build Colony Ship</Btn>
          ) : (
            <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>Build a shipyard to construct colony ships.</span>
          )}
        </div>
      )}

      <Card style={{ padding: 0, marginBottom: 28 }}>
        {stationedColonyShips.length === 0 ? (
          <EmptyState title="No colony ships stationed" body="Colony ships transfer population to newly claimed territories." />
        ) : (
          <Table headers={['Location', 'Cargo', 'Pop Available', 'Actions']}>
            {stationedColonyShips.map(s => (
              <Tr key={s.id}>
                <Td>{s.origin_name || s.origin_node_key}</Td>
                <Td accent="teal">{s.cargo_population} / 100</Td>
                <Td muted>{s.origin_current_population ?? '—'}</Td>
                <Td>
                  <ColonyShipActions ship={s} ownedTerritories={ownedTerritories} onAction={load} />
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      {transitColonyShips.length > 0 && (
        <>
          <SectionLabel>Colony Ships in Transit</SectionLabel>
          <Card style={{ padding: 0, marginBottom: 28 }}>
            <Table headers={['Cargo', 'From', 'To', 'Arrives']}>
              {transitColonyShips.map(s => (
                <Tr key={s.id}>
                  <Td accent="amber">{s.cargo_population} / 100</Td>
                  <Td muted>{s.origin_name || s.origin_node_key}</Td>
                  <Td>{s.destination_name || s.destination_node_key}</Td>
                  <Td muted>{s.arrives_at ? new Date(s.arrives_at).toLocaleString() : '—'}</Td>
                </Tr>
              ))}
            </Table>
          </Card>
        </>
      )}

      <SectionLabel>Active Operations</SectionLabel>
      <Card style={{ padding: 0, marginBottom: 28 }}>
        {activeOpFleets.length === 0 ? (
          <EmptyState
            title="No active operations"
            body="Fleets pending confirmation or engaged at enemy territories appear here."
          />
        ) : (
          <Table headers={['Fleet', 'At', 'Status', 'Actions']}>
            {activeOpFleets.map(f => {
              const loc = f.destination_name || f.destination_node_key || '—'
              const pending = fleetActionPending[f.id]
              const err = fleetActionErrors[f.id]
              let statusEl, actions

              if (f.status === 'pending_confirmation') {
                const expiresAt = f.confirmation_expires_at ? new Date(f.confirmation_expires_at) : null
                statusEl = (
                  <span>
                    <Badge color="amber">Awaiting confirmation</Badge>
                    {expiresAt && (
                      <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 8 }}>
                        expires {expiresAt.toLocaleString()}
                      </span>
                    )}
                  </span>
                )
                actions = (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <Btn variant="danger" onClick={() => handleFleetAction(f.id, 'confirm-attack')} disabled={!!pending} style={{ padding: '3px 10px', fontSize: 12 }}>
                      {pending === 'confirm-attack' ? '…' : 'Confirm Attack'}
                    </Btn>
                    <Btn variant="ghost" onClick={() => handleFleetAction(f.id, 'recall')} disabled={!!pending} style={{ padding: '3px 10px', fontSize: 12 }}>
                      {pending === 'recall' ? '…' : 'Recall'}
                    </Btn>
                  </div>
                )
              } else if (f.status === 'engaged') {
                const hasDefenders = f.destination_has_defenders
                statusEl = hasDefenders
                  ? <Badge color="rose">In combat</Badge>
                  : <Badge color="teal">Undefended — draining resources</Badge>
                actions = (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {!hasDefenders && (
                      <Btn variant="amber" onClick={() => handleFleetAction(f.id, 'conquer')} disabled={!!pending} style={{ padding: '3px 10px', fontSize: 12 }}>
                        {pending === 'conquer' ? '…' : 'Conquer'}
                      </Btn>
                    )}
                    <Btn variant="ghost" onClick={() => handleFleetAction(f.id, 'recall')} disabled={!!pending} style={{ padding: '3px 10px', fontSize: 12 }}>
                      {pending === 'recall' ? '…' : 'Recall'}
                    </Btn>
                  </div>
                )
              } else {
                // holding
                statusEl = <Badge color="muted">Holding</Badge>
                actions = (
                  <Btn variant="ghost" onClick={() => handleFleetAction(f.id, 'recall')} disabled={!!pending} style={{ padding: '3px 10px', fontSize: 12 }}>
                    {pending === 'recall' ? '…' : 'Recall'}
                  </Btn>
                )
              }

              return (
                <Tr key={f.id}>
                  <Td accent="amber">{f.unit_count} fighters</Td>
                  <Td>{loc}</Td>
                  <Td>{statusEl}</Td>
                  <Td>
                    {actions}
                    {err && <p style={{ color: 'var(--danger)', fontSize: 12, marginTop: 4 }}>{err}</p>}
                  </Td>
                </Tr>
              )
            })}
          </Table>
        )}
      </Card>

      <SectionLabel>Active Wars</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['Nation', 'Declared', 'Status', 'Your Losses', 'Their Losses', 'Actions']}>
          <Tr>
            <Td colSpan={6} style={{ textAlign: 'center', padding: '40px 0' }}>
              <EmptyState title="No active wars" />
            </Td>
          </Tr>
        </Table>
      </Card>
    </div>
  )
}
