import { useState, useEffect, useCallback } from 'react'
import { Card, SectionLabel, EmptyState, Table, Tr, Td, Badge, Btn, StatCard } from '../components/ui'

const UNIT_LABELS = { starfighter: 'Starfighter' }

function ManufactureForm({ unit, factoryTerritories, onManufactured, onCancel }) {
  const [quantity, setQuantity] = useState(1)
  const [territoryId, setTerritoryId] = useState(factoryTerritories[0]?.id ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const mineralCost = unit.manufacture_cost_minerals * quantity
  const fuelCost = unit.manufacture_cost_fuel * quantity

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
          ATK {unit.attack} · DEF {unit.defense} · HP {unit.hp}
        </span>
      </div>
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Build at</div>
          <select
            value={territoryId}
            onChange={e => setTerritoryId(e.target.value)}
            style={{ padding: '6px 10px', background: 'var(--bg-base)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}
          >
            {factoryTerritories.map(t => (
              <option key={t.id} value={t.id}>{t.territory_name || t.territory_node_key}</option>
            ))}
          </select>
        </div>
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
          Cost: {mineralCost} minerals, {fuelCost} fuel
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

export default function Military() {
  const [units, setUnits] = useState([])
  const [fleets, setFleets] = useState([])
  const [facilities, setFacilities] = useState([])
  const [nation, setNation] = useState(null)
  const [loading, setLoading] = useState(true)
  const [manufacturingUnit, setManufacturingUnit] = useState(null)

  const load = useCallback(async () => {
    try {
      const [uRes, nRes, fRes, facRes] = await Promise.all([
        fetch('/api/military/units', { credentials: 'include' }),
        fetch('/api/nations/mine', { credentials: 'include' }),
        fetch('/api/military/fleets', { credentials: 'include' }),
        fetch('/api/facilities', { credentials: 'include' }),
      ])
      const [u, n, f, fac] = await Promise.all([uRes.json(), nRes.json(), fRes.json(), facRes.json()])
      setUnits(u)
      setNation(n)
      setFleets(f)
      setFacilities(fac)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleManufactured = () => {
    setManufacturingUnit(null)
    load()
  }

  if (loading) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  const stationedFleets = fleets.filter(f => f.status === 'stationed')
  const transitFleets = fleets.filter(f => f.status === 'in_transit')
  const totalUnits = fleets.reduce((s, f) => s + f.unit_count, 0)

  // Territories that have a fighter factory (for manufacture form)
  const factoryTerritories = facilities.filter(f => f.type === 'fighter_factory')

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
        <StatCard label="Minerals" value={nation ? parseFloat(nation.minerals).toFixed(0) : '—'} accent="var(--amber)" />
        <StatCard label="Fuel" value={nation ? parseFloat(nation.fuel).toFixed(0) : '—'} accent="var(--teal)" />
      </div>

      <SectionLabel>Unit Types</SectionLabel>

      {manufacturingUnit && (
        <ManufactureForm
          unit={manufacturingUnit}
          factoryTerritories={factoryTerritories}
          onManufactured={handleManufactured}
          onCancel={() => setManufacturingUnit(null)}
        />
      )}

      <Card style={{ padding: 0, marginBottom: 28 }}>
        {units.length === 0 ? (
          <EmptyState title="No unit types available" body="Build a fighter factory to unlock starfighters." />
        ) : (
          <Table headers={['Unit', 'ATK', 'DEF', 'HP', 'Speed', 'Manufacture Cost', '']}>
            {units.map(u => (
              <Tr key={u.type}>
                <Td><Badge color="rose">{UNIT_LABELS[u.type] || u.type}</Badge></Td>
                <Td>{u.attack}</Td>
                <Td>{u.defense}</Td>
                <Td>{u.hp}</Td>
                <Td muted>{u.nodes_per_tick} node{u.nodes_per_tick !== 1 ? 's' : ''}/tick</Td>
                <Td muted>{u.manufacture_cost_minerals}M / {u.manufacture_cost_fuel}F</Td>
                <Td>
                  {factoryTerritories.length > 0 ? (
                    <Btn
                      variant="ghost"
                      onClick={() => setManufacturingUnit(manufacturingUnit?.type === u.type ? null : u)}
                      style={{ padding: '3px 10px', fontSize: 12 }}
                    >
                      Manufacture
                    </Btn>
                  ) : (
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>No factory</span>
                  )}
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <SectionLabel>Stationed Fleets</SectionLabel>
      <Card style={{ padding: 0, marginBottom: 28 }}>
        {stationedFleets.length === 0 ? (
          <EmptyState title="No stationed fighters" body="Manufacture starfighters at a fighter factory. Use the map to deploy them." />
        ) : (
          <Table headers={['Territory', 'Fighters', 'Actions']}>
            {stationedFleets.map(f => (
              <Tr key={f.id}>
                <Td>{f.origin_name || f.origin_node_key}</Td>
                <Td accent="teal">{f.unit_count}</Td>
                <Td>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Use the Map to deploy</span>
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

      <SectionLabel>Confirmation Windows</SectionLabel>
      <Card>
        <EmptyState
          title="No pending confirmations"
          body="Fleets arriving at your territories will appear here. You have 4 hours (2 ticks) to confirm or recall before standing orders execute."
        />
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
