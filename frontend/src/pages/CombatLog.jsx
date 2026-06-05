import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { Card, SectionLabel, Btn } from '../components/ui'

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmt(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function fmtDuration(seconds) {
  if (seconds == null) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h >= 48) return `${Math.floor(h / 24)}d ${h % 24}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function num(v, decimals = 0) {
  if (v == null || v === 0) return '0'
  return Number(v).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  })
}

// ── Status bar chip ───────────────────────────────────────────────────────────

function StatusChip({ isActive, isPending }) {
  if (isPending) {
    return (
      <span style={{
        display: 'inline-block', padding: '2px 10px', borderRadius: 10,
        fontSize: 11, fontWeight: 700, letterSpacing: '0.06em',
        background: 'rgba(232,148,58,0.15)', color: 'var(--amber)',
        border: '1px solid rgba(232,148,58,0.3)',
      }}>
        PENDING
      </span>
    )
  }
  if (isActive) {
    return (
      <span style={{
        display: 'inline-block', padding: '2px 10px', borderRadius: 10,
        fontSize: 11, fontWeight: 700, letterSpacing: '0.06em',
        background: 'rgba(192,114,106,0.15)', color: '#c0726a',
        border: '1px solid rgba(192,114,106,0.3)',
      }}>
        ACTIVE
      </span>
    )
  }
  return (
    <span style={{
      display: 'inline-block', padding: '2px 10px', borderRadius: 10,
      fontSize: 11, fontWeight: 700, letterSpacing: '0.06em',
      background: 'var(--bg-hover)', color: 'var(--text-muted)',
      border: '1px solid var(--border)',
    }}>
      ENDED
    </span>
  )
}

// ── Stat column ───────────────────────────────────────────────────────────────

function StatRow({ label, a, b, higherIsBetter = false, unit = '' }) {
  const aNum = Number(a) || 0
  const bNum = Number(b) || 0
  const aWorse = higherIsBetter ? aNum < bNum : aNum > bNum
  const bWorse = higherIsBetter ? bNum < aNum : bNum > aNum

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '1fr 180px 1fr',
      alignItems: 'center',
      padding: '8px 0',
      borderBottom: '1px solid var(--border)',
      fontSize: 13,
    }}>
      <div style={{
        fontWeight: 600,
        color: aWorse ? '#c0726a' : aNum > 0 ? 'var(--text-primary)' : 'var(--text-muted)',
        textAlign: 'right',
        paddingRight: 20,
      }}>
        {num(a)}{unit}
      </div>
      <div style={{
        textAlign: 'center',
        color: 'var(--text-muted)',
        fontSize: 11,
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
      }}>
        {label}
      </div>
      <div style={{
        fontWeight: 600,
        color: bWorse ? '#c0726a' : bNum > 0 ? 'var(--text-primary)' : 'var(--text-muted)',
        paddingLeft: 20,
      }}>
        {num(b)}{unit}
      </div>
    </div>
  )
}

function SectionDivider({ label }) {
  return (
    <div style={{
      padding: '14px 0 6px',
      fontSize: 10,
      textTransform: 'uppercase',
      letterSpacing: '0.12em',
      color: 'var(--text-muted)',
      textAlign: 'center',
      borderBottom: '1px solid var(--border)',
    }}>
      {label}
    </div>
  )
}

// ── War scoreboard ────────────────────────────────────────────────────────────

function Scoreboard({ status, nationName, opponentName, myId, oppId }) {
  const ns = status.nation_stats
  const os = status.opponent_stats

  // Total economic damage = war cost (fighters) + resources stolen from this nation
  const nTotalLoss = ns.war_cost_minerals + ns.war_cost_fuel + ns.minerals_lost + ns.fuel_lost
  const oTotalLoss = os.war_cost_minerals + os.war_cost_fuel + os.minerals_lost + os.fuel_lost

  return (
    <Card style={{ padding: '20px 28px' }}>
      {/* Column headers */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 180px 1fr',
        marginBottom: 8,
      }}>
        <div style={{
          textAlign: 'right', paddingRight: 20,
          fontWeight: 600, fontSize: 14,
          color: status.declared_by_nation_id === myId ? '#c0726a' : 'var(--text-primary)',
        }}>
          {nationName}
          {status.declared_by_nation_id === myId && (
            <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 6 }}>declared</span>
          )}
        </div>
        <div />
        <div style={{
          paddingLeft: 20,
          fontWeight: 600, fontSize: 14,
          color: status.declared_by_nation_id === oppId ? '#c0726a' : 'var(--text-primary)',
        }}>
          {opponentName}
          {status.declared_by_nation_id === oppId && (
            <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 6 }}>declared</span>
          )}
        </div>
      </div>

      <SectionDivider label="Combat" />
      <StatRow label="Fighters Lost"      a={ns.fighter_losses}     b={os.fighter_losses}     />
      <StatRow label="Planets Conquered"  a={ns.planets_gained}     b={os.planets_gained}     higherIsBetter />
      <StatRow label="Planets Lost"       a={ns.planets_lost}       b={os.planets_lost}       />
      <StatRow label="Territories Gained" a={ns.territories_gained} b={os.territories_gained} higherIsBetter />
      <StatRow label="Territories Lost"   a={ns.territories_lost}   b={os.territories_lost}   />

      <SectionDivider label="War Cost (Fighters)" />
      <StatRow label="Minerals Spent"     a={ns.war_cost_minerals}  b={os.war_cost_minerals}  />
      <StatRow label="Fuel Spent"         a={ns.war_cost_fuel}      b={os.war_cost_fuel}       />
      <StatRow label="Credits Spent"      a={ns.war_cost_currency}  b={os.war_cost_currency}   />

      <SectionDivider label="Occupation Drain" />
      <StatRow label="Minerals Stolen"    a={ns.minerals_stolen}  b={os.minerals_stolen}  higherIsBetter />
      <StatRow label="Fuel Stolen"        a={ns.fuel_stolen}      b={os.fuel_stolen}      higherIsBetter />
      <StatRow label="Minerals Lost"      a={ns.minerals_lost}    b={os.minerals_lost}    />
      <StatRow label="Fuel Lost"          a={ns.fuel_lost}        b={os.fuel_lost}        />

      <SectionDivider label="Total Economic Damage" />
      <StatRow label="Resources Lost (min+fuel)" a={nTotalLoss} b={oTotalLoss} />
    </Card>
  )
}

// ── Combat log (collapsible) ──────────────────────────────────────────────────

function CombatRoundRow({ ev, nationName, opponentName }) {
  const p = ev.payload
  const location = p.territory_name || p.territory_node_key || `Territory #${p.territory_id}`
  const attIsNation = parseInt(p.attacker_nation_id) !== parseInt(p.defender_nation_id)
  const attackerName = parseInt(p.attacker_nation_id) > parseInt(p.defender_nation_id) ? opponentName : nationName
  // Use nation IDs from payload to decide names
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12,
      padding: '10px 0', borderBottom: '1px solid var(--border)', fontSize: 13,
    }}>
      <div style={{ color: 'var(--text-muted)', fontSize: 12, gridColumn: '1 / -1', marginBottom: 2 }}>
        Combat at <span style={{ color: 'var(--text-secondary)' }}>{location}</span>
      </div>
      <div>
        <span style={{ color: 'var(--text-secondary)' }}>Attacker</span>
        <span style={{ color: 'var(--danger)', marginLeft: 8 }}>−{p.attacker_losses} fighters</span>
        <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 6 }}>({p.attacker_remaining} left)</span>
      </div>
      <div>
        <span style={{ color: 'var(--text-secondary)' }}>Defender</span>
        <span style={{ color: 'var(--danger)', marginLeft: 8 }}>−{p.defender_losses} fighters</span>
        <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 6 }}>({p.defender_remaining} left)</span>
      </div>
    </div>
  )
}

function DrainRow({ ev }) {
  const p = ev.payload
  const location = p.territory_name || p.territory_node_key || `Territory #${p.territory_id}`
  return (
    <div style={{ padding: '10px 0', borderBottom: '1px solid var(--border)', fontSize: 13 }}>
      <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 4 }}>
        Occupation at <span style={{ color: 'var(--text-secondary)' }}>{location}</span>
      </div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {p.minerals_drained > 0 && (
          <span>
            <span style={{ color: 'var(--amber)' }}>−{p.minerals_drained} minerals</span>
            <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 4 }}>drained</span>
          </span>
        )}
        {p.fuel_drained > 0 && (
          <span>
            <span style={{ color: 'var(--teal)' }}>−{p.fuel_drained} fuel</span>
            <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 4 }}>drained</span>
          </span>
        )}
      </div>
    </div>
  )
}

function EventLog({ nationId, opponentId }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = () => {
    if (data !== null) return
    setLoading(true)
    fetch(`/api/nations/${nationId}/wars/${opponentId}/log`, { credentials: 'include' })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => { setError('Failed to load events'); setLoading(false) })
  }

  const toggle = () => {
    if (!open) load()
    setOpen(o => !o)
  }

  const grouped = []
  if (data?.events) {
    let cur = null
    for (const ev of data.events) {
      if (!cur || cur.tickAt !== ev.tick_at) {
        cur = { tickAt: ev.tick_at, events: [] }
        grouped.push(cur)
      }
      cur.events.push(ev)
    }
  }

  return (
    <div style={{ marginTop: 28 }}>
      <Card style={{ padding: 0 }}>
        <button
          onClick={toggle}
          style={{
            width: '100%', display: 'flex', alignItems: 'center',
            justifyContent: 'space-between', padding: '14px 20px',
            background: 'transparent', border: 'none', cursor: 'pointer',
            borderBottom: open ? '1px solid var(--border)' : 'none',
          }}
        >
          <span style={{ fontWeight: 500, fontSize: 13, color: 'var(--text-primary)' }}>Combat Event Log</span>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{open ? '▲' : '▼'}</span>
        </button>

        {open && (
          <div style={{ padding: '12px 20px' }}>
            {loading && <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading…</p>}
            {error && <p style={{ color: 'var(--danger)', fontSize: 13 }}>{error}</p>}
            {data && grouped.length === 0 && (
              <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>No combat events recorded yet.</p>
            )}
            {grouped.map(g => (
              <div key={g.tickAt} style={{ marginBottom: 24 }}>
                <div style={{
                  fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase',
                  letterSpacing: '0.08em', marginBottom: 8,
                }}>
                  {fmt(g.tickAt)}
                </div>
                {g.events.map((ev, i) =>
                  ev.type === 'combat_round'
                    ? <CombatRoundRow key={i} ev={ev} nationName={data.nation_name} opponentName={data.opponent_name} />
                    : <DrainRow key={i} ev={ev} />
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WarStatus() {
  const { id, opponentId } = useParams()
  const navigate = useNavigate()
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(`/api/nations/${id}/wars/${opponentId}/status`, { credentials: 'include' })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => { setStatus(d); setLoading(false) })
      .catch(() => { setError('Failed to load war status'); setLoading(false) })
  }, [id, opponentId])

  if (loading) return <p style={{ color: 'var(--text-muted)', padding: 40 }}>Loading…</p>
  if (error) return (
    <div style={{ padding: 40 }}>
      <div style={{ color: 'var(--danger)', marginBottom: 16 }}>{error}</div>
      <Btn variant="ghost" onClick={() => navigate(-1)}>← Back</Btn>
    </div>
  )

  const isPending = !status.started_at
  const myId = parseInt(id)
  const oppId = parseInt(opponentId)

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <Btn variant="ghost" onClick={() => navigate(`/nations/${id}`)}>
          ← {status.nation_name}
        </Btn>
      </div>

      {/* War header */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
          <h1 style={{ fontSize: 22, fontWeight: 600 }}>
            <Link to={`/nations/${id}`} style={{ color: 'var(--text-primary)' }}>
              {status.nation_name}
            </Link>
            {' '}
            <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>vs</span>
            {' '}
            <Link to={`/nations/${opponentId}`} style={{ color: 'var(--text-primary)' }}>
              {status.opponent_name}
            </Link>
          </h1>
          <StatusChip isActive={status.is_active} isPending={isPending} />
        </div>

        <div style={{
          display: 'flex', gap: 28, fontSize: 12, color: 'var(--text-muted)', flexWrap: 'wrap',
        }}>
          <span>
            Declared <span style={{ color: 'var(--text-secondary)' }}>{fmt(status.declared_at)}</span>
          </span>
          {status.started_at && (
            <span>
              Started <span style={{ color: 'var(--text-secondary)' }}>{fmt(status.started_at)}</span>
            </span>
          )}
          {status.ended_at && (
            <span>
              Ended <span style={{ color: 'var(--text-secondary)' }}>{fmt(status.ended_at)}</span>
            </span>
          )}
          <span>
            Duration{' '}
            <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>
              {isPending ? 'War not yet active' : fmtDuration(status.elapsed_seconds)}
            </span>
          </span>
        </div>
      </div>

      {isPending ? (
        <Card>
          <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>
            War declaration is pending. Hostilities have not begun. No combat statistics yet.
          </p>
        </Card>
      ) : (
        <>
          <SectionLabel>War Statistics</SectionLabel>
          <Scoreboard
            status={status}
            nationName={status.nation_name}
            opponentName={status.opponent_name}
            myId={myId}
            oppId={oppId}
          />
          <EventLog nationId={id} opponentId={opponentId} />
        </>
      )}
    </div>
  )
}
