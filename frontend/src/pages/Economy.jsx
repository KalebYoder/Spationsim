import { useState, useEffect, useCallback } from 'react'
import { StatCard, Card, SectionLabel, EmptyState, Table, Tr, Td } from '../components/ui'

const PRODUCTION = { mine: { minerals: 5, fuel: 0 }, refinery: { minerals: 0, fuel: 5 } }
const fmt = n => Number(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })

function useCountdown(targetMs) {
  const [remaining, setRemaining] = useState(targetMs - Date.now())
  useEffect(() => {
    const id = setInterval(() => setRemaining(targetMs - Date.now()), 1000)
    return () => clearInterval(id)
  }, [targetMs])
  const secs = Math.max(0, Math.floor(remaining / 1000))
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  const s = secs % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export default function Economy() {
  const [nation, setNation] = useState(null)
  const [facilities, setFacilities] = useState([])
  const [territories, setTerritories] = useState([])
  const [lastTickAt, setLastTickAt] = useState(null)
  const [population, setPopulation] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    const [nRes, fRes, tRes, eRes, pRes] = await Promise.all([
      fetch('/api/nations/mine', { credentials: 'include' }),
      fetch('/api/facilities', { credentials: 'include' }),
      fetch('/api/nations/mine/territories', { credentials: 'include' }),
      fetch('/api/economy/last-tick', { credentials: 'include' }),
      fetch('/api/economy/population', { credentials: 'include' }),
    ])
    const [n, f, t, e, p] = await Promise.all([
      nRes.json(), fRes.json(), tRes.json(),
      eRes.ok ? eRes.json() : null,
      pRes.ok ? pRes.json() : null,
    ])
    setNation(n)
    setFacilities(f)
    setTerritories(t)
    if (e?.processed_at) setLastTickAt(new Date(e.processed_at).getTime())
    if (p) setPopulation(p)
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const nextTickMs = lastTickAt ? lastTickAt + 2 * 60 * 60 * 1000 : null
  const countdown = useCountdown(nextTickMs ?? Date.now())

  if (loading) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  // Per-territory production
  const byTerritory = territories.map(t => {
    const terFacilities = facilities.filter(f => f.territory_id === t.id)
    const minerals = terFacilities.reduce((s, f) => s + (PRODUCTION[f.type]?.minerals ?? 0), 0)
    const fuel = terFacilities.reduce((s, f) => s + (PRODUCTION[f.type]?.fuel ?? 0), 0)
    return { ...t, minerals_per_tick: minerals, fuel_per_tick: fuel }
  })

  const totalMineralsPerTick = byTerritory.reduce((s, t) => s + t.minerals_per_tick, 0)
  const totalFuelPerTick = byTerritory.reduce((s, t) => s + t.fuel_per_tick, 0)

  return (
    <div>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 22, fontWeight: 600 }}>Economy</h1>
        <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
          Resource stockpiles, per-tick production, and population overview
        </p>
      </div>

      <SectionLabel>Stockpiles</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14 }}>
        <StatCard
          label="Minerals"
          value={fmt(nation?.minerals)}
          sub={`+${totalMineralsPerTick} per tick`}
          accent="var(--amber)"
        />
        <StatCard
          label="Fuel"
          value={fmt(nation?.fuel)}
          sub={`+${totalFuelPerTick} per tick`}
          accent="var(--teal)"
        />
        <StatCard
          label="Next Tick"
          value={nextTickMs ? countdown : '—'}
          sub={lastTickAt ? `Last: ${new Date(lastTickAt).toLocaleTimeString()}` : 'No ticks yet'}
        />
      </div>

      <SectionLabel>Population</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14 }}>
        <StatCard label="Total Population" value={population ? fmt(population.total) : '—'} accent="var(--purple)" />
        <StatCard label="Assigned" value={population ? fmt(population.assigned) : '—'} sub="staffing infrastructure" />
        <StatCard label="Unassigned" value={population ? fmt(population.unassigned) : '—'} sub="available to assign" accent="var(--teal)" />
      </div>

      <SectionLabel>Production by Territory</SectionLabel>
      <Card style={{ padding: 0 }}>
        {byTerritory.length === 0 ? (
          <EmptyState title="No territories" body="Colonize territories to see production breakdown." />
        ) : (
          <Table headers={['Territory', 'Minerals / tick', 'Fuel / tick', 'Distance']}>
            {byTerritory.map(t => (
              <Tr key={t.id}>
                <Td>{t.name || t.node_key}</Td>
                <Td accent={t.minerals_per_tick > 0 ? 'amber' : undefined}>{t.minerals_per_tick}</Td>
                <Td accent={t.fuel_per_tick > 0 ? 'teal' : undefined}>{t.fuel_per_tick}</Td>
                <Td muted>{t.distance_from_center}</Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <SectionLabel>Spending</SectionLabel>
      <Card>
        <EmptyState
          title="No active spending"
          body="Fleet upkeep and infrastructure maintenance costs will appear here."
        />
      </Card>
    </div>
  )
}
