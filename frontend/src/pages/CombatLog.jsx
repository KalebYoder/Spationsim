import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { Card, SectionLabel, Btn } from '../components/ui'

function fmt(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function CombatRoundRow({ ev, nationName, opponentName }) {
  const p = ev.payload
  const attackerIsNation = p.attacker_nation_id === undefined
    ? false
    : String(p.attacker_nation_id) !== String(p.defender_nation_id)

  const location = p.territory_name || p.territory_node_key || `Territory #${p.territory_id}`

  const attackerName = attackerIsNation ? nationName : opponentName
  const defenderName = attackerIsNation ? opponentName : nationName

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 12,
      padding: '10px 0',
      borderBottom: '1px solid var(--border)',
      fontSize: 13,
    }}>
      <div style={{ color: 'var(--text-muted)', fontSize: 12, gridColumn: '1 / -1', marginBottom: 2 }}>
        Combat at <span style={{ color: 'var(--text-secondary)' }}>{location}</span>
      </div>
      <div>
        <span style={{ color: 'var(--text-secondary)' }}>{attackerName}</span>
        <span style={{ color: 'var(--danger)', marginLeft: 8 }}>
          −{p.attacker_losses} fighters
        </span>
        <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 6 }}>
          ({p.attacker_remaining} remaining)
        </span>
      </div>
      <div>
        <span style={{ color: 'var(--text-secondary)' }}>{defenderName}</span>
        <span style={{ color: 'var(--danger)', marginLeft: 8 }}>
          −{p.defender_losses} fighters
        </span>
        <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 6 }}>
          ({p.defender_remaining} remaining)
        </span>
      </div>
    </div>
  )
}

function DrainRow({ ev, nationName, opponentName }) {
  const p = ev.payload
  const location = p.territory_name || p.territory_node_key || `Territory #${p.territory_id}`

  // The attacker is draining the defender's resources
  const attackerNationId = p.attacker_nation_id
  const defenderNationId = p.defender_nation_id

  return (
    <div style={{
      padding: '10px 0',
      borderBottom: '1px solid var(--border)',
      fontSize: 13,
    }}>
      <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 4 }}>
        Occupation at <span style={{ color: 'var(--text-secondary)' }}>{location}</span>
      </div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {p.minerals_drained > 0 && (
          <span>
            <span style={{ color: 'var(--amber)' }}>−{p.minerals_drained} minerals</span>
            <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 4 }}>drained from defender</span>
          </span>
        )}
        {p.fuel_drained > 0 && (
          <span>
            <span style={{ color: 'var(--teal)' }}>−{p.fuel_drained} fuel</span>
            <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 4 }}>drained from defender</span>
          </span>
        )}
      </div>
    </div>
  )
}

function TickGroup({ tickAt, events, nationName, opponentName }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{
        fontSize: 11,
        color: 'var(--text-muted)',
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
        marginBottom: 8,
      }}>
        {fmt(tickAt)}
      </div>
      {events.map((ev, i) =>
        ev.type === 'combat_round'
          ? <CombatRoundRow key={i} ev={ev} nationName={nationName} opponentName={opponentName} />
          : <DrainRow key={i} ev={ev} nationName={nationName} opponentName={opponentName} />
      )}
    </div>
  )
}

export default function CombatLog() {
  const { id, opponentId } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(`/api/nations/${id}/wars/${opponentId}/log`, { credentials: 'include' })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => { setData(d); setLoading(false) })
      .catch(() => { setError('Failed to load combat log'); setLoading(false) })
  }, [id, opponentId])

  if (loading) return <p style={{ color: 'var(--text-muted)', padding: 40 }}>Loading…</p>
  if (error) return (
    <div style={{ padding: 40 }}>
      <div style={{ color: 'var(--danger)', marginBottom: 16 }}>{error}</div>
      <Btn variant="ghost" onClick={() => navigate(-1)}>← Back</Btn>
    </div>
  )

  // Group events by tick_at
  const grouped = []
  let cur = null
  for (const ev of data.events) {
    if (!cur || cur.tickAt !== ev.tick_at) {
      cur = { tickAt: ev.tick_at, events: [] }
      grouped.push(cur)
    }
    cur.events.push(ev)
  }

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Btn variant="ghost" onClick={() => navigate(`/nations/${id}`)}>
          ← Back to {data.nation_name}
        </Btn>
      </div>

      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 22, fontWeight: 600 }}>
          {data.nation_name} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>vs</span> {data.opponent_name}
        </h1>
        <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
          Full combat history between these two nations
        </p>
      </div>

      {grouped.length === 0 ? (
        <Card>
          <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>No combat events recorded between these nations.</p>
        </Card>
      ) : (
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, fontSize: 13, color: 'var(--text-muted)' }}>
            <span>{data.events.length} event{data.events.length !== 1 ? 's' : ''}</span>
            <span>{grouped.length} tick{grouped.length !== 1 ? 's' : ''}</span>
          </div>
          {grouped.map(g => (
            <TickGroup
              key={g.tickAt}
              tickAt={g.tickAt}
              events={g.events}
              nationName={data.nation_name}
              opponentName={data.opponent_name}
            />
          ))}
        </Card>
      )}
    </div>
  )
}
