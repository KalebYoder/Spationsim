import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import { PageHeader, StatCard, Card, SectionLabel, EmptyState, Btn, Badge } from '../components/ui'

const fmt = n => Number(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })

function fmtDatetime(iso) {
  return iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : null
}

function timeUntil(iso) {
  if (!iso) return null
  const ms = new Date(iso) - Date.now()
  if (ms <= 0) return null
  const h = Math.floor(ms / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

function VacationPanel({ nation, onRefresh }) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const inVacation = nation?.vacation_mode
  const lockoutUntil = nation?.aggression_lockout_until
  const inLockout = lockoutUntil && new Date(lockoutUntil) > new Date()
  const vacationSince = nation?.vacation_since
  const earliestExit = vacationSince
    ? new Date(new Date(vacationSince).getTime() + 48 * 3600 * 1000)
    : null
  const canExitNow = earliestExit && new Date() >= earliestExit
  const exitUnlockIn = earliestExit ? timeUntil(earliestExit.toISOString()) : null

  const act = async (path) => {
    setSubmitting(true)
    setError('')
    try {
      const r = await fetch(path, { method: 'POST', credentials: 'include' })
      if (!r.ok) {
        const d = await r.json()
        setError(d.detail || 'Failed')
        return
      }
      onRefresh()
    } catch {
      setError('Network error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card style={{ marginBottom: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ fontWeight: 500, marginBottom: 4 }}>
            Vacation Mode&nbsp;
            {inVacation && <Badge color="teal">Active</Badge>}
            {!inVacation && inLockout && <Badge color="amber">Lockout</Badge>}
            {!inVacation && !inLockout && <Badge color="neutral">Inactive</Badge>}
          </div>
          {inVacation && (
            <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
              Entered {fmtDatetime(vacationSince)}.&nbsp;
              {canExitNow
                ? 'Minimum stay met — you can exit now.'
                : `Minimum stay ends in ${exitUnlockIn}.`}
            </div>
          )}
          {!inVacation && inLockout && (
            <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
              Post-vacation lockout: fleet dispatch and vacation re-entry blocked for {timeUntil(lockoutUntil)} (until {fmtDatetime(lockoutUntil)}).
            </div>
          )}
          {!inVacation && !inLockout && (
            <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
              Entering vacation mode protects your nation. Minimum 48-hour stay. A 48-hour aggression lockout applies on exit.
            </div>
          )}
        </div>
        <div>
          {inVacation ? (
            <Btn
              variant="ghost"
              onClick={() => act('/api/nations/me/vacation/exit')}
              disabled={submitting || !canExitNow}
            >
              {submitting ? 'Exiting…' : canExitNow ? 'Exit Vacation' : `Exit in ${exitUnlockIn}`}
            </Btn>
          ) : (
            <Btn
              variant="ghost"
              onClick={() => act('/api/nations/me/vacation/enter')}
              disabled={submitting || !!inLockout}
            >
              {submitting ? 'Entering…' : inLockout ? `Locked out` : 'Enter Vacation'}
            </Btn>
          )}
        </div>
      </div>
      {error && <p style={{ color: 'var(--danger)', fontSize: 13, marginTop: 8 }}>{error}</p>}
    </Card>
  )
}

function EconomyBreakdown({ yields }) {
  if (!yields || yields.length === 0) return null

  const minerals = yields.reduce((s, y) => s + (y.minerals_per_tick || 0), 0)
  const fuelGross = yields.reduce((s, y) => s + (y.fuel_per_tick || 0), 0)
  const fuelUpkeep = yields.reduce((s, y) => s + (y.logistics_fuel_upkeep_per_tick || 0), 0)
  const fuelNet = yields.reduce((s, y) => s + (y.fuel_net_per_tick ?? y.fuel_per_tick ?? 0), 0)
  const currencyIncome = yields.reduce((s, y) => s + (y.currency_income_per_tick || 0), 0)
  const fighterUpkeep = yields.reduce((s, y) => s + (y.currency_upkeep_per_tick || 0), 0)
  const territoryUpkeep = yields.reduce((s, y) => s + (y.territory_upkeep_currency_per_tick || 0), 0)
  const currencyNet = yields.reduce((s, y) => s + (y.currency_net_per_tick || 0), 0)

  const Row = ({ label, value, unit, color, indent }) => (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, fontSize: 13, paddingLeft: indent ? 16 : 0 }}>
      <span style={{ color: 'var(--text-secondary)', minWidth: indent ? 150 : 166 }}>{label}</span>
      <span style={{ color: color || 'var(--text-primary)', fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>{value}</span>
      <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{unit}</span>
    </div>
  )

  const sign = v => v >= 0 ? `+${v}` : `${v}`

  return (
    <Card style={{ marginBottom: 0 }}>
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 14 }}>Per-Tick Economy</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 20 }}>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Minerals</div>
          <Row label="Production" value={sign(minerals)} unit="min/t" color="var(--amber)" />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Fuel</div>
          <Row label="Production" value={sign(fuelGross)} unit="fuel/t" color="var(--teal)" />
          {fuelUpkeep > 0 && <Row label="Logistics upkeep" value={`−${fuelUpkeep}`} unit="fuel/t" color="var(--danger)" indent />}
          {fuelUpkeep > 0 && <Row label="Net" value={sign(fuelNet)} unit="fuel/t" color={fuelNet >= 0 ? 'var(--teal)' : 'var(--danger)'} />}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Currency</div>
          <Row label="Facility income" value={sign(currencyIncome)} unit="¤/t" color="var(--teal)" />
          {fighterUpkeep > 0 && <Row label="Fighter upkeep" value={`−${fighterUpkeep}`} unit="¤/t" color="var(--danger)" indent />}
          {territoryUpkeep > 0 && <Row label="Territory upkeep" value={`−${territoryUpkeep}`} unit="¤/t" color="var(--danger)" indent />}
          <Row label="Net" value={sign(currencyNet)} unit="¤/t" color={currencyNet >= 0 ? 'var(--teal)' : 'var(--danger)'} />
        </div>

      </div>
    </Card>
  )
}

export default function Home() {
  const { player } = useAuth()
  const [nation, setNation] = useState(null)
  const [yields, setYields] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const [nRes, yRes] = await Promise.all([
        fetch('/api/nations/mine', { credentials: 'include' }),
        fetch('/api/nations/mine/territories/yields', { credentials: 'include' }),
      ])
      if (nRes.ok) setNation(await nRes.json())
      if (yRes.ok) setYields(await yRes.json())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  return (
    <div>
      <PageHeader
        title={nation ? nation.name : `Welcome, ${player?.username}`}
        sub={nation ? `Currency: ${nation.currency_name}` : undefined}
      />

      <SectionLabel>Active Alerts</SectionLabel>
      <Card style={{ marginBottom: 0 }}>
        <EmptyState
          title="No active alerts"
          body="Confirmation windows, incoming fleets, and war declarations will appear here."
        />
      </Card>

      <SectionLabel>Resources</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 14 }}>
        <StatCard
          label="Minerals"
          value={fmt(nation?.minerals)}
          sub={yields ? `+${yields.reduce((s, y) => s + (y.minerals_per_tick || 0), 0)}/tick` : 'per tick: —'}
          accent="var(--amber)"
        />
        <StatCard
          label="Fuel"
          value={fmt(nation?.fuel)}
          sub={yields ? (() => { const n = yields.reduce((s, y) => s + (y.fuel_net_per_tick ?? y.fuel_per_tick ?? 0), 0); return `${n >= 0 ? '+' : ''}${n}/tick (net)` })() : 'per tick: —'}
          accent="var(--teal)"
        />
        <StatCard label="Population" value="—" sub="unassigned: —" accent="var(--purple)" />
        <StatCard label="Territories" value="—" />
        <StatCard
          label="Currency"
          value={fmt(nation?.currency)}
          sub={yields ? (() => { const n = yields.reduce((s, y) => s + (y.currency_net_per_tick || 0), 0); return `${n >= 0 ? '+' : ''}${n}/tick (net)` })() : 'per tick: —'}
          accent="var(--amber)"
        />
      </div>

      <SectionLabel>Economy</SectionLabel>
      <EconomyBreakdown yields={yields} />

      <SectionLabel>Power</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 14 }}>
        <StatCard
          label="Military Strength"
          value={fmt(nation?.military_strength)}
          sub="1 per fighter"
          accent="var(--danger, #c0726a)"
        />
        <StatCard
          label="Industrial Strength"
          value={fmt(nation?.industrial_strength)}
          sub="mines +1 · refineries +1 · shipyards +2"
          accent="var(--teal)"
        />
      </div>

      <SectionLabel>Vacation Mode</SectionLabel>
      <VacationPanel nation={nation} onRefresh={load} />

      <SectionLabel>Recent Events</SectionLabel>
      <Card>
        <EmptyState
          title="No recent events"
          body="Probe arrivals, fleet movements, and construction completions will appear here."
        />
      </Card>
    </div>
  )
}
