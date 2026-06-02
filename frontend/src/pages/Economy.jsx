import { useState, useEffect, useCallback } from 'react'
import { StatCard, Card, SectionLabel, EmptyState, Table, Tr, Td } from '../components/ui'

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

function FlowRow({ label, value, positive, zero }) {
  const color = zero ? 'var(--text-muted)'
    : positive ? 'var(--teal)' : 'var(--danger)'
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '5px 0', borderBottom: '1px solid var(--border)', fontSize: 13 }}>
      <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
      <span style={{ color, fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>{zero ? '0' : value}</span>
    </div>
  )
}

function FlowCard({ label, accent, rows, net, runway }) {
  const netSign = net >= 0 ? '+' : ''
  const netColor = net >= 0 ? 'var(--teal)' : 'var(--danger)'
  return (
    <Card>
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 12 }}>
        {label} / tick
      </div>
      <div>
        {rows.map((r, i) => <FlowRow key={i} {...r} />)}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', paddingTop: 8, marginTop: 2 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Net</span>
        <div style={{ textAlign: 'right' }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: netColor, fontVariantNumeric: 'tabular-nums' }}>
            {netSign}{net}
          </span>
          {runway && (
            <span style={{ fontSize: 11, color: 'var(--danger)', marginLeft: 8 }}>
              empty in {runway} tick{runway !== 1 ? 's' : ''} ({Math.round(runway * 2)}h)
            </span>
          )}
        </div>
      </div>
    </Card>
  )
}

export default function Economy() {
  const [nation, setNation] = useState(null)
  const [facilities, setFacilities] = useState([])
  const [territories, setTerritories] = useState([])
  const [lastTickAt, setLastTickAt] = useState(null)
  const [population, setPopulation] = useState(null)
  const [flow, setFlow] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    const [nRes, fRes, tRes, eRes, pRes, flowRes] = await Promise.all([
      fetch('/api/nations/mine', { credentials: 'include' }),
      fetch('/api/facilities', { credentials: 'include' }),
      fetch('/api/nations/mine/territories', { credentials: 'include' }),
      fetch('/api/economy/last-tick', { credentials: 'include' }),
      fetch('/api/economy/population', { credentials: 'include' }),
      fetch('/api/economy/flow', { credentials: 'include' }),
    ])
    const [n, f, t, e, p, fl] = await Promise.all([
      nRes.json(), fRes.json(), tRes.json(),
      eRes.ok ? eRes.json() : null,
      pRes.ok ? pRes.json() : null,
      flowRes.ok ? flowRes.json() : null,
    ])
    setNation(n)
    setFacilities(f)
    setTerritories(t)
    if (e?.processed_at) setLastTickAt(new Date(e.processed_at).getTime())
    if (p) setPopulation(p)
    if (fl) setFlow(fl)
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const nextTickMs = lastTickAt ? lastTickAt + 2 * 60 * 60 * 1000 : null
  const countdown = useCountdown(nextTickMs ?? Date.now())

  if (loading) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  // Per-territory production: round(2 × richness) per facility
  const byTerritory = territories.map(t => {
    const terFacilities = facilities.filter(f => f.territory_id === t.id)
    const minerals = terFacilities.reduce((s, f) =>
      f.type === 'mine' ? s + Math.round(2 * (t.mineral_richness ?? 0)) : s, 0)
    const fuel = terFacilities.reduce((s, f) =>
      f.type === 'refinery' ? s + Math.round(2 * (t.fuel_richness ?? 0)) : s, 0)
    const pop_cap = Math.round(50 * ((t.mineral_richness ?? 0) + (t.fuel_richness ?? 0)))
    return { ...t, minerals_per_tick: minerals, fuel_per_tick: fuel, pop_cap }
  })

  const totalMineralsPerTick = flow?.minerals?.production_per_tick
    ?? byTerritory.reduce((s, t) => s + t.minerals_per_tick, 0)
  const totalFuelPerTick = flow?.fuel?.production_per_tick
    ?? byTerritory.reduce((s, t) => s + t.fuel_per_tick, 0)

  const fuelNet = flow?.fuel?.net_per_tick ?? null
  const fuelNetSign = fuelNet === null ? '' : fuelNet >= 0 ? '+' : ''
  const fuelNetColor = fuelNet === null ? 'var(--text-muted)'
    : fuelNet >= 0 ? 'var(--teal)' : 'var(--danger)'
  const fuelRunway = flow?.fuel?.ticks_until_empty

  const currencyNet = flow?.currency?.net_per_tick ?? null
  const currencyNetSign = currencyNet === null ? '' : currencyNet >= 0 ? '+' : ''
  const currencyNetColor = currencyNet === null ? 'var(--text-muted)'
    : currencyNet >= 0 ? 'var(--teal)' : 'var(--danger)'
  const currencyRunway = flow?.currency?.ticks_until_empty

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
          sub={
            fuelNet !== null
              ? (fuelRunway
                  ? `${fuelNetSign}${fuelNet}/tick · empty in ${fuelRunway} ticks`
                  : `${fuelNetSign}${fuelNet}/tick`)
              : `+${totalFuelPerTick} per tick`
          }
          accent="var(--teal)"
          subColor={fuelNetColor}
        />
        <StatCard
          label={nation?.currency_name || 'Currency'}
          value={fmt(nation?.currency)}
          sub={
            currencyNet !== null
              ? (currencyRunway
                  ? `${currencyNetSign}${currencyNet}/tick · empty in ${currencyRunway} ticks`
                  : `${currencyNetSign}${currencyNet}/tick`)
              : undefined
          }
          subColor={currencyNetColor}
        />
        <StatCard
          label="Next Tick"
          value={nextTickMs ? countdown : '—'}
          sub={lastTickAt ? `Last: ${new Date(lastTickAt).toLocaleTimeString()}` : 'No ticks yet'}
        />
      </div>

      <SectionLabel>Population</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14 }}>
        <StatCard
          label="Total Population"
          value={population ? fmt(population.total) : '—'}
          sub={population?.cap ? `Cap: ${fmt(population.cap)}` : undefined}
          accent="var(--purple)"
        />
        <StatCard label="Assigned" value={population ? fmt(population.assigned) : '—'} sub="staffing infrastructure" />
        <StatCard label="Unassigned" value={population ? fmt(population.unassigned) : '—'} sub="available to assign" accent="var(--teal)" />
      </div>

      <SectionLabel>Production by Territory</SectionLabel>
      <Card style={{ padding: 0 }}>
        {byTerritory.length === 0 ? (
          <EmptyState title="No territories" body="Colonize territories to see production breakdown." />
        ) : (
          <Table headers={['Territory', 'Minerals / tick', 'Fuel / tick', 'Pop Cap', 'Distance']}>
            {byTerritory.map(t => (
              <Tr key={t.id}>
                <Td>{t.name || t.node_key}</Td>
                <Td accent={t.minerals_per_tick > 0 ? 'amber' : undefined}>{t.minerals_per_tick}</Td>
                <Td accent={t.fuel_per_tick > 0 ? 'teal' : undefined}>{t.fuel_per_tick}</Td>
                <Td accent="purple">{fmt(t.pop_cap)}</Td>
                <Td muted>{t.distance_from_center}</Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <SectionLabel>Resource Flow</SectionLabel>
      {flow ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <FlowCard
            label="Fuel"
            accent="var(--teal)"
            rows={[
              { label: 'Refineries', value: `+${flow.fuel.production_per_tick}`, positive: true, zero: flow.fuel.production_per_tick === 0 },
              { label: `Fleet upkeep (${flow.fuel.fleet_count_out_of_dock} fighters out of dock)`, value: `-${flow.fuel.fleet_upkeep_per_tick}`, positive: false, zero: flow.fuel.fleet_upkeep_per_tick === 0 },
              { label: `Logistics (${flow.fuel.territory_count} territories)`, value: `-${flow.fuel.logistics_upkeep_per_tick}`, positive: false, zero: flow.fuel.logistics_upkeep_per_tick === 0 },
            ]}
            net={flow.fuel.net_per_tick}
            runway={flow.fuel.ticks_until_empty}
          />
          <FlowCard
            label={nation?.currency_name || 'Currency'}
            accent="var(--amber)"
            rows={[
              { label: `Active facilities (${flow.currency.income_facility_count} mines/refineries)`, value: `+${flow.currency.income_per_tick}`, positive: true },
              { label: `Fighter upkeep (${flow.currency.total_fighters} fighters)`, value: `-${flow.currency.fighter_upkeep_per_tick}`, positive: false, zero: flow.currency.fighter_upkeep_per_tick === 0 },
              { label: `Territory upkeep (${flow.currency.territory_count}² × 10)`, value: `-${flow.currency.territory_upkeep_per_tick}`, positive: false, zero: flow.currency.territory_upkeep_per_tick === 0 },
            ]}
            net={flow.currency.net_per_tick}
            runway={flow.currency.ticks_until_empty}
          />
        </div>
      ) : (
        <Card>
          <EmptyState title="No flow data" body="Colonize territories to see resource flow." />
        </Card>
      )}
    </div>
  )
}
