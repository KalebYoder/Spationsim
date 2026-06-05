import { useState, useEffect, useCallback } from 'react'
import { Card, SectionLabel, EmptyState } from '../components/ui'
import { useTutorial } from '../hooks/useTutorial'

const EVENT_LABELS = {
  fleet_stationed:                    'Fleet arrived',
  fleet_arrived_at_enemy_territory:   'Fleet at enemy territory (awaiting confirmation)',
  enemy_fleet_arrived:                'Enemy fleet arrived at your territory',
  fleet_recalled_on_expiry:           'Fleet recalled (confirmation expired)',
  fleet_holding_at_enemy_territory:   'Fleet holding at enemy territory',
  probe_stationed:                    'Probe arrived',
  probe_destroyed_in_enemy_territory: 'Probe destroyed in enemy territory',
  enemy_probe_detected_and_destroyed: 'Enemy probe detected and destroyed',
  colony_ship_stationed:              'Colony ship arrived',
  dissent_threshold_crossed:          'Dissent threshold crossed',
}

function fmtDelta(val, prefix = '') {
  if (val === null || val === undefined || val === 0) return null
  const n = Number(val)
  return `${prefix}${n > 0 ? '+' : ''}${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}

function fmtTime(isoStr) {
  const d = new Date(isoStr)
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function EconomyRow({ economy }) {
  if (!economy) return null
  const items = [
    fmtDelta(economy.minerals_delta, '') && `Minerals ${fmtDelta(economy.minerals_delta)}`,
    fmtDelta(economy.fuel_delta, '') && `Fuel ${fmtDelta(economy.fuel_delta)}`,
    fmtDelta(economy.currency_delta, '') && `Currency ${fmtDelta(economy.currency_delta)}`,
    fmtDelta(economy.population_delta, '') && `Population ${fmtDelta(economy.population_delta)}`,
  ].filter(Boolean)

  if (items.length === 0) return null
  return (
    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 6 }}>
      {items.join(' · ')}
    </div>
  )
}

function EventLine({ ev }) {
  const label = EVENT_LABELS[ev.type] ?? ev.type
  const p = ev.payload ?? {}

  let detail = ''
  if (ev.type === 'fleet_stationed') {
    detail = p.territory_node_key
      ? ` — ${p.unit_count ?? '?'} units at ${p.territory_node_key}`
      : ''
  } else if (ev.type === 'probe_stationed') {
    detail = p.territory_node_key ? ` — ${p.territory_node_key}` : ''
  } else if (ev.type === 'colony_ship_stationed') {
    detail = p.territory_node_key ? ` — ${p.territory_node_key}` : ''
  } else if (ev.type === 'enemy_fleet_arrived') {
    detail = p.node_key ? ` — your territory at ${p.node_key}` : ''
  } else if (ev.type === 'probe_destroyed_in_enemy_territory') {
    detail = p.territory_node_key ? ` — at ${p.territory_node_key}` : ''
  } else if (ev.type === 'dissent_threshold_crossed') {
    const loc = p.node_key || p.territory_node_key || ''
    const dir = p.direction === 'rising' ? 'rising' : 'falling'
    detail = loc ? ` — ${loc} dissent ${dir} through ${p.threshold}` : ` — dissent ${dir} through ${p.threshold}`
  }

  const isHostile = [
    'enemy_fleet_arrived',
    'probe_destroyed_in_enemy_territory',
  ].includes(ev.type)

  const isWarning = ev.type === 'dissent_threshold_crossed' && ev.payload?.direction === 'rising'
  const isRecovery = ev.type === 'dissent_threshold_crossed' && ev.payload?.direction === 'falling'

  const color = isHostile ? 'var(--red, #e05252)'
    : isWarning ? 'var(--amber, #d4a017)'
    : isRecovery ? 'var(--teal, #3eb89a)'
    : 'var(--text-primary)'
  const borderColor = isHostile ? 'var(--red, #e05252)'
    : isWarning ? 'var(--amber, #d4a017)'
    : isRecovery ? 'var(--teal, #3eb89a)'
    : 'var(--border)'

  return (
    <div style={{
      fontSize: 12,
      color,
      paddingLeft: 8,
      borderLeft: `2px solid ${borderColor}`,
      marginBottom: 4,
    }}>
      {label}{detail}
    </div>
  )
}

function TickEntry({ entry }) {
  return (
    <div style={{
      borderBottom: '1px solid var(--border)',
      paddingBottom: 14,
      marginBottom: 14,
    }}>
      <div style={{
        fontSize: 11,
        color: 'var(--text-muted)',
        marginBottom: 6,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
      }}>
        {fmtTime(entry.tick_at)}
      </div>
      <EconomyRow economy={entry.economy} />
      {entry.events.map((ev, i) => (
        <EventLine key={i} ev={ev} />
      ))}
      {!entry.economy && entry.events.length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No activity</div>
      )}
    </div>
  )
}

export default function EventLog() {
  const [log, setLog] = useState(null)
  const { tutorial, refresh } = useTutorial()

  const load = useCallback(async () => {
    const r = await fetch('/api/events/log', { credentials: 'include' })
    if (r.ok) setLog(await r.json())
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (tutorial?.current_step === 6) {
      fetch('/api/tutorial/complete-step-6', { method: 'POST', credentials: 'include' })
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data) refresh() })
        .catch(() => {})
    }
  }, [tutorial?.current_step])

  if (log === null) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  return (
    <>
      <SectionLabel>Event Log</SectionLabel>
      <p style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 20 }}>
        A record of what happened each tick — production, fleet arrivals, probe activity.
      </p>
      <Card>
        {log.length === 0
          ? <EmptyState>No events recorded yet. Events appear here after the first tick.</EmptyState>
          : log.map((entry, i) => <TickEntry key={i} entry={entry} />)
        }
      </Card>
    </>
  )
}
