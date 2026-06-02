import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useNation } from '../hooks/useNation'
import { diploColor } from '../hooks/useDiplomacy'
import { PageHeader, Card, SectionLabel, Badge, Btn } from '../components/ui'

const TRADE_STYLE = { color: '#7aafb8', border: '#2a4e5a', bg: '#0e1f24' }

const WAR_STYLE    = { color: '#c0726a', bg: '#2e1515', border: '#6b2a2a' }
const FRIEND_STYLE = { color: '#5a8a62', bg: '#152318', border: '#2a4e30' }

function WarSection({ status, nationName, onDeclareWar }) {
  const [confirmingWar, setConfirmingWar] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleDeclare = async () => {
    setSaving(true)
    setError('')
    const err = await onDeclareWar()
    if (err) setError(err)
    setSaving(false)
    setConfirmingWar(false)
  }

  if (status === 'war') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: WAR_STYLE.color }}>At War</span>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Propose peace terms via the Trade page
          </span>
        </div>
      </div>
    )
  }

  if (status === 'war_pending') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#9e5a2a' }}>War Declared</span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Hostilities begin in ~4 hours</span>
      </div>
    )
  }

  return (
    <div style={{ position: 'relative' }}>
      <button
        disabled={saving}
        onClick={() => setConfirmingWar(true)}
        style={{
          padding: '7px 14px',
          borderRadius: 'var(--radius-sm)',
          border: `1px solid ${WAR_STYLE.border}`,
          background: 'transparent',
          color: WAR_STYLE.color,
          fontSize: 13,
          fontWeight: 600,
          cursor: saving ? 'not-allowed' : 'pointer',
          opacity: saving ? 0.6 : 1,
        }}
      >
        Declare War
      </button>

      {confirmingWar && (
        <div style={{
          position: 'absolute',
          top: 'calc(100% + 4px)',
          right: 0,
          zIndex: 100,
          width: 240,
          background: 'var(--bg-surface)',
          border: `1px solid ${WAR_STYLE.border}`,
          borderRadius: 'var(--radius-sm)',
          boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
          padding: '14px 16px',
        }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: WAR_STYLE.color, marginBottom: 6 }}>
            Declare war on {nationName}?
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 14, lineHeight: 1.5 }}>
            Hostilities begin in 4 hours. War cannot end for 24 hours after declaration.
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => setConfirmingWar(false)}
              style={{
                flex: 1, padding: '6px 0',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border)',
                background: 'transparent',
                color: 'var(--text-secondary)',
                fontSize: 13, cursor: 'pointer',
              }}
            >
              Cancel
            </button>
            <button
              disabled={saving}
              onClick={handleDeclare}
              style={{
                flex: 1, padding: '6px 0',
                borderRadius: 'var(--radius-sm)',
                border: `1px solid ${WAR_STYLE.border}`,
                background: WAR_STYLE.bg,
                color: WAR_STYLE.color,
                fontSize: 13, fontWeight: 600,
                cursor: saving ? 'not-allowed' : 'pointer',
              }}
            >
              {saving ? 'Declaring…' : 'Declare War'}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', right: 0, zIndex: 100,
          background: 'var(--bg-surface)', border: '1px solid var(--danger)',
          borderRadius: 'var(--radius-sm)', padding: '8px 12px',
          fontSize: 12, color: 'var(--danger)', maxWidth: 260, whiteSpace: 'pre-wrap',
        }}>
          {error}
          <button
            onClick={() => setError('')}
            style={{ display: 'block', marginTop: 6, fontSize: 11, color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  )
}

function FriendSection({ status, requestedBy, myNationId, targetNationId, onAction }) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  if (status === 'war' || status === 'war_pending') return null

  const act = async (endpoint, method = 'POST') => {
    setSaving(true)
    setError('')
    const err = await onAction(endpoint, method)
    if (err) setError(err)
    setSaving(false)
  }

  let content
  if (status === 'friendly') {
    content = (
      <button
        disabled={saving}
        onClick={() => act('remove-friend')}
        style={{
          padding: '7px 14px',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border)',
          background: 'transparent',
          color: 'var(--text-secondary)',
          fontSize: 13,
          cursor: saving ? 'not-allowed' : 'pointer',
          opacity: saving ? 0.6 : 1,
        }}
      >
        {saving ? 'Removing…' : 'Remove from friends list'}
      </button>
    )
  } else if (status === 'friend_pending' && requestedBy === myNationId) {
    content = (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>Request Sent</span>
        <button
          disabled={saving}
          onClick={() => act('refuse-friend')}
          style={{
            padding: '5px 10px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)',
            background: 'transparent',
            color: 'var(--text-muted)',
            fontSize: 12,
            cursor: saving ? 'not-allowed' : 'pointer',
            opacity: saving ? 0.6 : 1,
          }}
        >
          Cancel
        </button>
      </div>
    )
  } else if (status === 'friend_pending' && requestedBy !== myNationId) {
    content = (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>Friend Request Received</span>
        <button
          disabled={saving}
          onClick={() => act('accept-friend')}
          style={{
            padding: '6px 12px',
            borderRadius: 'var(--radius-sm)',
            border: `1px solid ${FRIEND_STYLE.border}`,
            background: FRIEND_STYLE.bg,
            color: FRIEND_STYLE.color,
            fontSize: 13, fontWeight: 600,
            cursor: saving ? 'not-allowed' : 'pointer',
            opacity: saving ? 0.6 : 1,
          }}
        >
          Accept
        </button>
        <button
          disabled={saving}
          onClick={() => act('refuse-friend')}
          style={{
            padding: '6px 12px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)',
            background: 'transparent',
            color: 'var(--text-muted)',
            fontSize: 13,
            cursor: saving ? 'not-allowed' : 'pointer',
            opacity: saving ? 0.6 : 1,
          }}
        >
          Refuse
        </button>
      </div>
    )
  } else {
    content = (
      <button
        disabled={saving}
        onClick={() => act('friend-request')}
        style={{
          padding: '7px 14px',
          borderRadius: 'var(--radius-sm)',
          border: `1px solid ${FRIEND_STYLE.border}`,
          background: 'transparent',
          color: FRIEND_STYLE.color,
          fontSize: 13, fontWeight: 600,
          cursor: saving ? 'not-allowed' : 'pointer',
          opacity: saving ? 0.6 : 1,
        }}
      >
        {saving ? 'Sending…' : 'Add to friends list'}
      </button>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
      {content}
      {error && <div style={{ fontSize: 12, color: 'var(--danger)', maxWidth: 260, textAlign: 'right' }}>{error}</div>}
    </div>
  )
}

function fmtDate(iso) {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function WarHistory({ nationId }) {
  const [open, setOpen] = useState(false)
  const [wars, setWars] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const toggle = () => {
    setOpen(o => {
      if (!o && wars === null) {
        setLoading(true)
        fetch(`/api/nations/${nationId}/wars`, { credentials: 'include' })
          .then(r => r.ok ? r.json() : Promise.reject())
          .then(d => { setWars(d); setLoading(false) })
          .catch(() => { setError('Failed to load war history'); setLoading(false) })
      }
      return !o
    })
  }

  return (
    <div>
      <SectionLabel>War History</SectionLabel>
      <Card style={{ padding: 0 }}>
        <button
          onClick={toggle}
          style={{
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '14px 20px',
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--text-secondary)',
            fontSize: 13,
            borderBottom: open ? '1px solid var(--border)' : 'none',
          }}
        >
          <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>View Past Wars</span>
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{open ? '▲' : '▼'}</span>
        </button>

        {open && (
          <div style={{ padding: '12px 20px' }}>
            {loading && <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading…</p>}
            {error && <p style={{ color: 'var(--danger)', fontSize: 13 }}>{error}</p>}
            {wars && wars.length === 0 && (
              <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>No war history.</p>
            )}
            {wars && wars.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {wars.map((w, i) => (
                  <div
                    key={i}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '10px 14px',
                      background: 'var(--bg-hover)',
                      borderRadius: 'var(--radius-sm)',
                      border: `1px solid ${w.is_active ? 'rgba(192,114,106,0.3)' : 'var(--border)'}`,
                    }}
                  >
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        {w.is_active && (
                          <span style={{
                            fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
                            color: WAR_STYLE.color, letterSpacing: '0.08em',
                          }}>
                            Active
                          </span>
                        )}
                        <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>
                          vs {w.opponent_name}
                        </span>
                      </div>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {fmtDate(w.declared_at)}
                        {w.ended_at ? ` — ${fmtDate(w.ended_at)}` : w.is_active ? ' — ongoing' : ''}
                      </span>
                    </div>
                    <Link
                      to={`/nations/${nationId}/wars/${w.opponent_id}`}
                      style={{
                        fontSize: 12,
                        color: 'var(--teal)',
                        textDecoration: 'none',
                        padding: '5px 10px',
                        border: '1px solid var(--border)',
                        borderRadius: 'var(--radius-sm)',
                      }}
                    >
                      View Log →
                    </Link>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}

export default function NationProfile() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { nation: myNation } = useNation()
  const [profile, setProfile] = useState(null)
  const [diplo, setDiplo] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const nationId = parseInt(id)
  const isOwnNation = myNation?.id === nationId

  const loadProfile = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [profResp, diploResp] = await Promise.all([
        fetch(`/api/nations/${nationId}`, { credentials: 'include' }),
        isOwnNation ? Promise.resolve(null) : fetch(`/api/diplomacy/${nationId}`, { credentials: 'include' }),
      ])
      if (!profResp.ok) { setError('Nation not found'); return }
      setProfile(await profResp.json())
      if (diploResp && diploResp.ok) setDiplo(await diploResp.json())
    } finally {
      setLoading(false)
    }
  }, [nationId, isOwnNation])

  useEffect(() => { loadProfile() }, [loadProfile])

  const handleDeclareWar = async () => {
    const r = await fetch(`/api/diplomacy/${nationId}`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'war' }),
    })
    const data = await r.json()
    if (!r.ok) return data.detail || 'Failed to declare war'
    setDiplo(d => ({ ...d, status: data.status }))
    return null
  }

  const handleFriendAction = async (endpoint) => {
    const r = await fetch(`/api/diplomacy/${nationId}/${endpoint}`, {
      method: 'POST',
      credentials: 'include',
    })
    const data = await r.json()
    if (!r.ok) return data.detail || 'Action failed'
    // Re-fetch diplo state so requested_by is current
    const diploResp = await fetch(`/api/diplomacy/${nationId}`, { credentials: 'include' })
    if (diploResp.ok) setDiplo(await diploResp.json())
    return null
  }

  if (loading) return <div style={{ padding: 40, color: 'var(--text-muted)' }}>Loading…</div>
  if (error) return (
    <div style={{ padding: 40 }}>
      <div style={{ color: 'var(--danger)', marginBottom: 16 }}>{error}</div>
      <Btn variant="ghost" onClick={() => navigate(-1)}>← Back</Btn>
    </div>
  )
  if (!profile) return null

  const flagColor = profile.flag_color || '#3A86FF'
  const currentStatus = diplo?.status || 'neutral'
  const requestedBy = diplo?.requested_by ?? null

  return (
    <div>
      <PageHeader
        title={profile.name}
        sub={profile.vacation_mode ? 'Currently in vacation mode' : 'Active nation'}
      />

      <Card>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 20 }}>
          <div style={{
            width: 48, height: 48,
            borderRadius: 'var(--radius-sm)',
            background: flagColor,
            flexShrink: 0,
            border: '2px solid var(--border)',
          }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 18, marginBottom: 4, color: isOwnNation ? 'var(--text-primary)' : diploColor(currentStatus) }}>{profile.name}</div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
              {profile.currency_name} · {profile.territory_count} {profile.territory_count === 1 ? 'territory' : 'territories'}
            </div>
          </div>

          {isOwnNation ? (
            <Badge color="teal">Your Nation</Badge>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10 }}>
              <WarSection
                status={currentStatus}
                nationName={profile.name}
                onDeclareWar={handleDeclareWar}
              />
              <FriendSection
                status={currentStatus}
                requestedBy={requestedBy}
                myNationId={myNation?.id}
                targetNationId={nationId}
                onAction={handleFriendAction}
              />
              {currentStatus !== 'war' && currentStatus !== 'war_pending' && (
                <button
                  onClick={() => navigate(`/trade?with=${nationId}`)}
                  style={{
                    padding: '7px 14px',
                    borderRadius: 'var(--radius-sm)',
                    border: `1px solid ${TRADE_STYLE.border}`,
                    background: 'transparent',
                    color: TRADE_STYLE.color,
                    fontSize: 13,
                    cursor: 'pointer',
                  }}
                >
                  Propose Trade
                </button>
              )}
            </div>
          )}
        </div>

        {profile.vacation_mode && (
          <div style={{
            marginTop: 14,
            padding: '8px 12px',
            background: 'rgba(255,200,100,0.08)',
            border: '1px solid rgba(255,200,100,0.2)',
            borderRadius: 'var(--radius-sm)',
            fontSize: 13,
            color: 'var(--text-secondary)',
          }}>
            This nation is in vacation mode and cannot be declared war on.
          </div>
        )}
      </Card>

      <SectionLabel>Power</SectionLabel>
      <Card>
        <div style={{ display: 'flex', gap: 40, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Military Strength</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--text-primary)' }}>
              {(profile.military_strength ?? 0).toLocaleString()}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Industrial Strength</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--text-primary)' }}>
              {(profile.industrial_strength ?? 0).toLocaleString()}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Starfighters</div>
            <div style={{ fontSize: 24, fontWeight: 600, color: 'var(--text-secondary)' }}>
              {(profile.military?.starfighter ?? 0).toLocaleString()}
            </div>
          </div>
        </div>
      </Card>

      <WarHistory nationId={nationId} />
    </div>
  )
}
