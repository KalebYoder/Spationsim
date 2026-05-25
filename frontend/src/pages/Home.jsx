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

export default function Home() {
  const { player } = useAuth()
  const [nation, setNation] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const r = await fetch('/api/nations/mine', { credentials: 'include' })
      if (r.ok) setNation(await r.json())
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
        <StatCard label="Minerals" value={fmt(nation?.minerals)} sub="per tick: —" accent="var(--amber)" />
        <StatCard label="Fuel" value={fmt(nation?.fuel)} sub="per tick: —" accent="var(--teal)" />
        <StatCard label="Population" value="—" sub="unassigned: —" accent="var(--purple)" />
        <StatCard label="Territories" value="—" />
        <StatCard label="Military" value="—" sub="units" />
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
