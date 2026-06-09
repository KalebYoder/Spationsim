import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useNation } from '../hooks/useNation'
import { PageHeader, Card, SectionLabel, EmptyState, Table, Tr, Td, Btn } from '../components/ui'

const INPUT = {
  width: 90,
  padding: '5px 8px',
  background: 'var(--bg-base)',
  color: 'var(--text-primary)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-sm)',
  fontSize: 13,
  textAlign: 'right',
}

const CONFIRM_COOLDOWN = 5  // seconds, must match backend

function ResourceLine({ minerals, fuel, currency, label }) {
  const parts = []
  if (minerals) parts.push(`${minerals} minerals`)
  if (fuel)     parts.push(`${fuel} fuel`)
  if (currency) parts.push(`${currency} currency`)
  const text = parts.length ? parts.join(' · ') : '—'
  return (
    <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
      <span style={{ color: 'var(--text-muted)', marginRight: 4 }}>{label}</span>
      {text}
    </span>
  )
}

function ProposeForm({ nations, myNation, onProposed }) {
  const [searchParams] = useSearchParams()
  const [toId, setToId]                     = useState(searchParams.get('with') || '')
  const [route, setRoute]                   = useState(null)
  const [routeLoading, setRL]               = useState(false)
  const [offerMin,  setOfferMin]            = useState(0)
  const [offerFuel, setOfferFuel]           = useState(0)
  const [offerCur,  setOfferCur]            = useState(0)
  const [reqMin,    setReqMin]              = useState(0)
  const [reqFuel,   setReqFuel]             = useState(0)
  const [reqCur,    setReqCur]              = useState(0)
  const [includesPeace, setIncludesPeace]           = useState(false)
  const [offerTerritoryId, setOfferTerritoryId]     = useState('')
  const [requestTerritoryId, setRequestTerritoryId] = useState('')
  const [myTerritories, setMyTerritories]           = useState([])
  const [theirTerritories, setTheirTerritories]     = useState([])
  const [warStatus, setWarStatus]                   = useState(false)
  const [myProbeData, setMyProbeData]               = useState([])
  const [offerProbeDataIds, setOfferProbeDataIds]   = useState([])
  const [submitting, setSub]                        = useState(false)
  const [error, setError]                           = useState('')

  useEffect(() => {
    Promise.all([
      fetch('/api/nations/mine/territories', { credentials: 'include' }).then(r => r.ok ? r.json() : []),
      fetch('/api/probes/data', { credentials: 'include' }).then(r => r.ok ? r.json() : []),
    ]).then(([terr, probes]) => { setMyTerritories(terr); setMyProbeData(probes) })
  }, [])

  const checkRoute = useCallback(async (nationId) => {
    if (!nationId) { setRoute(null); setTheirTerritories([]); setWarStatus(false); return }
    setRL(true)
    const [rRes, tRes, dRes] = await Promise.all([
      fetch(`/api/trade/route/${nationId}`, { credentials: 'include' }),
      fetch(`/api/nations/${nationId}/territories`, { credentials: 'include' }),
      fetch(`/api/diplomacy/${nationId}`, { credentials: 'include' }),
    ])
    if (rRes.ok) setRoute(await rRes.json())
    if (tRes.ok) setTheirTerritories(await tRes.json())
    if (dRes.ok) {
      const d = await dRes.json()
      setWarStatus(d.status === 'war' || d.status === 'war_pending')
    }
    setRL(false)
  }, [])

  useEffect(() => { checkRoute(toId) }, [toId, checkRoute])

  const handleSubmit = async () => {
    setError('')
    setSub(true)
    try {
      const r = await fetch('/api/trade', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          to_nation_id: Number(toId),
          offer_minerals: offerMin,
          offer_fuel: offerFuel,
          offer_currency: offerCur,
          request_minerals: reqMin,
          request_fuel: reqFuel,
          request_currency: reqCur,
          includes_peace: includesPeace,
          offer_territory_id: offerTerritoryId ? Number(offerTerritoryId) : null,
          request_territory_id: requestTerritoryId ? Number(requestTerritoryId) : null,
          offer_probe_data_ids: offerProbeDataIds,
        }),
      })
      const data = await r.json()
      if (!r.ok) { setError(data.detail || 'Failed'); return }
      onProposed()
      setOfferMin(0); setOfferFuel(0); setOfferCur(0)
      setReqMin(0);   setReqFuel(0);   setReqCur(0)
      setIncludesPeace(false); setOfferTerritoryId(''); setRequestTerritoryId('')
      setOfferProbeDataIds([])
    } catch {
      setError('Network error')
    } finally {
      setSub(false)
    }
  }

  const routeStatus = () => {
    if (!toId) return null
    if (warStatus && includesPeace) return <span style={{ color: 'var(--teal)', fontSize: 12 }}>Peace negotiation — no trade route required</span>
    if (routeLoading) return <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>Checking route…</span>
    if (!route) return null
    if (route.has_route) return <span style={{ color: 'var(--teal)', fontSize: 12 }}>Route available</span>
    return <span style={{ color: 'var(--danger)', fontSize: 12 }}>No route — {route.reason}</span>
  }

  const toggleProbeData = id => setOfferProbeDataIds(prev =>
    prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
  )

  const hasTerms = offerMin || offerFuel || offerCur || reqMin || reqFuel || reqCur || includesPeace || offerTerritoryId || requestTerritoryId || offerProbeDataIds.length > 0
  const canSubmit = !submitting && toId && (includesPeace || route?.has_route) && hasTerms

  return (
    <Card style={{ marginBottom: 24 }}>
      <div style={{ fontWeight: 500, marginBottom: 16 }}>Propose a Trade</div>

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Trade with
          </div>
          <select
            value={toId}
            onChange={e => setToId(e.target.value)}
            style={{ ...INPUT, width: 180, textAlign: 'left' }}
          >
            <option value="">— Select nation —</option>
            {nations.map(n => (
              <option key={n.id} value={n.id}>{n.name}</option>
            ))}
          </select>
        </div>
        <div style={{ paddingBottom: 4 }}>{routeStatus()}</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
        <div>
          <div style={{ fontSize: 12, color: 'var(--amber)', marginBottom: 10, fontWeight: 600 }}>
            You offer
          </div>
          {[
            ['Minerals', offerMin,  setOfferMin,  parseFloat(myNation?.minerals || 0)],
            ['Fuel',     offerFuel, setOfferFuel, parseFloat(myNation?.fuel || 0)],
            ['Currency', offerCur,  setOfferCur,  parseFloat(myNation?.currency || 0)],
          ].map(([label, val, set, max]) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span style={{ fontSize: 13, color: 'var(--text-secondary)', width: 70 }}>{label}</span>
              <input
                type="number" min={0} max={max} value={val}
                onChange={e => set(Math.max(0, parseFloat(e.target.value) || 0))}
                style={INPUT}
              />
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>/ {Math.floor(max)}</span>
            </div>
          ))}
        </div>

        <div>
          <div style={{ fontSize: 12, color: 'var(--teal)', marginBottom: 10, fontWeight: 600 }}>
            You request
          </div>
          {[
            ['Minerals', reqMin,  setReqMin],
            ['Fuel',     reqFuel, setReqFuel],
            ['Currency', reqCur,  setReqCur],
          ].map(([label, val, set]) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span style={{ fontSize: 13, color: 'var(--text-secondary)', width: 70 }}>{label}</span>
              <input
                type="number" min={0} value={val}
                onChange={e => set(Math.max(0, parseFloat(e.target.value) || 0))}
                style={INPUT}
              />
            </div>
          ))}
        </div>
      </div>

      {warStatus && (
        <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="checkbox"
            id="peace-checkbox"
            checked={includesPeace}
            onChange={e => setIncludesPeace(e.target.checked)}
          />
          <label htmlFor="peace-checkbox" style={{ fontSize: 13, color: 'var(--text-secondary)', cursor: 'pointer' }}>
            Include peace terms (ends the war on acceptance)
          </label>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginTop: 12 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Offer territory (optional)
          </div>
          <select value={offerTerritoryId} onChange={e => setOfferTerritoryId(e.target.value)} style={{ ...INPUT, width: '100%', textAlign: 'left' }}>
            <option value="">— None —</option>
            {myTerritories.filter(t => t.is_owned).map(t => (
              <option key={t.id} value={t.id}>{t.name || t.node_key}</option>
            ))}
          </select>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Request territory (optional)
          </div>
          <select value={requestTerritoryId} onChange={e => setRequestTerritoryId(e.target.value)} style={{ ...INPUT, width: '100%', textAlign: 'left' }}>
            <option value="">— None —</option>
            {theirTerritories.filter(t => t.is_owned).map(t => (
              <option key={t.id} value={t.id}>{t.name || t.node_key}</option>
            ))}
          </select>
        </div>
      </div>

      {myProbeData.filter(pd => !pd.is_owned).length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Offer probe data (optional)
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 160, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
            {myProbeData.filter(pd => !pd.is_owned).map(pd => (
              <label key={pd.id} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
                <input
                  type="checkbox"
                  checked={offerProbeDataIds.includes(pd.id)}
                  onChange={() => toggleProbeData(pd.id)}
                />
                <span style={{ color: 'var(--amber)' }}>{Number(pd.mineral_richness).toFixed(1)}M</span>
                <span style={{ color: 'var(--teal)' }}>{Number(pd.fuel_richness).toFixed(1)}F</span>
                <span style={{ color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: 11 }}>{pd.node_key}</span>
                {pd.territory_name && <span style={{ color: 'var(--text-secondary)' }}>{pd.territory_name}</span>}
              </label>
            ))}
          </div>
        </div>
      )}

      <div style={{ marginTop: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
        <Btn variant="amber" onClick={handleSubmit} disabled={!canSubmit}>
          {submitting ? 'Sending…' : 'Propose Trade'}
        </Btn>
        {error && <span style={{ fontSize: 13, color: 'var(--danger)' }}>{error}</span>}
      </div>
    </Card>
  )
}

function useCountdown(targetIso) {
  const [remaining, setRemaining] = useState(0)

  useEffect(() => {
    if (!targetIso) { setRemaining(0); return }
    const target = new Date(targetIso).getTime() + CONFIRM_COOLDOWN * 1000

    const tick = () => {
      const diff = Math.ceil((target - Date.now()) / 1000)
      setRemaining(Math.max(0, diff))
    }
    tick()
    const id = setInterval(tick, 250)
    return () => clearInterval(id)
  }, [targetIso])

  return remaining
}

function ConfirmButton({ label, acceptedAt, confirmedAt, onAccept, disabled, color }) {
  const countdown = useCountdown(acceptedAt)
  const canConfirm = acceptedAt && !confirmedAt && countdown === 0

  if (confirmedAt) {
    return (
      <span style={{ fontSize: 12, color: 'var(--teal)', fontWeight: 600 }}>Confirmed</span>
    )
  }

  if (acceptedAt && !confirmedAt) {
    return (
      <button
        onClick={onAccept}
        disabled={disabled || !canConfirm}
        style={{
          padding: '4px 12px',
          borderRadius: 'var(--radius-sm)',
          border: `1px solid ${color === 'amber' ? 'var(--amber)' : '#2a4e30'}`,
          background: canConfirm ? (color === 'amber' ? 'rgba(255,176,0,0.15)' : '#152318') : 'transparent',
          color: canConfirm ? (color === 'amber' ? 'var(--amber)' : '#5a8a62') : 'var(--text-muted)',
          fontSize: 12, fontWeight: 600,
          cursor: canConfirm && !disabled ? 'pointer' : 'not-allowed',
          minWidth: 90,
        }}
      >
        {countdown > 0 ? `Confirm (${countdown}s)` : 'Confirm'}
      </button>
    )
  }

  return (
    <button
      onClick={onAccept}
      disabled={disabled}
      style={{
        padding: '4px 12px',
        borderRadius: 'var(--radius-sm)',
        border: `1px solid ${color === 'amber' ? 'var(--amber)' : '#2a4e30'}`,
        background: color === 'amber' ? 'rgba(255,176,0,0.1)' : '#152318',
        color: color === 'amber' ? 'var(--amber)' : '#5a8a62',
        fontSize: 12, fontWeight: 600,
        cursor: disabled ? 'not-allowed' : 'pointer',
        minWidth: 90,
      }}
    >
      {label}
    </button>
  )
}

function EditTradeForm({ trade, onEdited, onCancel }) {
  const [offerMin,  setOfferMin]  = useState(parseFloat(trade.offer_minerals))
  const [offerFuel, setOfferFuel] = useState(parseFloat(trade.offer_fuel))
  const [offerCur,  setOfferCur]  = useState(parseFloat(trade.offer_currency))
  const [reqMin,    setReqMin]    = useState(parseFloat(trade.request_minerals))
  const [reqFuel,   setReqFuel]   = useState(parseFloat(trade.request_fuel))
  const [reqCur,    setReqCur]    = useState(parseFloat(trade.request_currency))
  const [includesPeace, setIncludesPeace]           = useState(trade.includes_peace ?? false)
  const [offerTerritoryId, setOfferTerritoryId]     = useState(trade.offer_territory_id ?? '')
  const [requestTerritoryId, setRequestTerritoryId] = useState(trade.request_territory_id ?? '')
  const [fromTerritories, setFromTerritories]       = useState([])
  const [toTerritories, setToTerritories]           = useState([])
  const [saving, setSaving]       = useState(false)
  const [error, setError]         = useState('')

  useEffect(() => {
    Promise.all([
      fetch(`/api/nations/${trade.from_nation_id}/territories`, { credentials: 'include' }),
      fetch(`/api/nations/${trade.to_nation_id}/territories`, { credentials: 'include' }),
    ]).then(async ([fRes, tRes]) => {
      if (fRes.ok) setFromTerritories(await fRes.json())
      if (tRes.ok) setToTerritories(await tRes.json())
    })
  }, [trade.from_nation_id, trade.to_nation_id])

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      const r = await fetch(`/api/trade/${trade.id}`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          offer_minerals: offerMin,
          offer_fuel: offerFuel,
          offer_currency: offerCur,
          request_minerals: reqMin,
          request_fuel: reqFuel,
          request_currency: reqCur,
          includes_peace: includesPeace,
          offer_territory_id: offerTerritoryId ? Number(offerTerritoryId) : null,
          request_territory_id: requestTerritoryId ? Number(requestTerritoryId) : null,
        }),
      })
      const data = await r.json()
      if (!r.ok) { setError(data.detail || 'Failed'); return }
      onEdited(data)
    } catch {
      setError('Network error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ marginTop: 8, padding: 12, background: 'var(--bg-base)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--amber)', marginBottom: 6, fontWeight: 600 }}>Offer</div>
          {[['Min', offerMin, setOfferMin], ['Fuel', offerFuel, setOfferFuel], ['Cur', offerCur, setOfferCur]].map(([l, v, s]) => (
            <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span style={{ fontSize: 12, color: 'var(--text-muted)', width: 30 }}>{l}</span>
              <input type="number" min={0} value={v} onChange={e => s(Math.max(0, parseFloat(e.target.value) || 0))} style={{ ...INPUT, width: 80 }} />
            </div>
          ))}
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--teal)', marginBottom: 6, fontWeight: 600 }}>Request</div>
          {[['Min', reqMin, setReqMin], ['Fuel', reqFuel, setReqFuel], ['Cur', reqCur, setReqCur]].map(([l, v, s]) => (
            <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span style={{ fontSize: 12, color: 'var(--text-muted)', width: 30 }}>{l}</span>
              <input type="number" min={0} value={v} onChange={e => s(Math.max(0, parseFloat(e.target.value) || 0))} style={{ ...INPUT, width: 80 }} />
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
        <input
          type="checkbox"
          id={`peace-edit-${trade.id}`}
          checked={includesPeace}
          onChange={e => setIncludesPeace(e.target.checked)}
        />
        <label htmlFor={`peace-edit-${trade.id}`} style={{ fontSize: 12, color: 'var(--text-secondary)', cursor: 'pointer' }}>
          Include peace terms
        </label>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Offer territory</div>
          <select value={offerTerritoryId} onChange={e => setOfferTerritoryId(e.target.value)} style={{ ...INPUT, width: '100%', textAlign: 'left' }}>
            <option value="">— None —</option>
            {fromTerritories.filter(t => t.is_owned).map(t => (
              <option key={t.id} value={t.id}>{t.name || t.node_key}</option>
            ))}
          </select>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Request territory</div>
          <select value={requestTerritoryId} onChange={e => setRequestTerritoryId(e.target.value)} style={{ ...INPUT, width: '100%', textAlign: 'left' }}>
            <option value="">— None —</option>
            {toTerritories.filter(t => t.is_owned).map(t => (
              <option key={t.id} value={t.id}>{t.name || t.node_key}</option>
            ))}
          </select>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Btn variant="amber" onClick={handleSave} disabled={saving}>Save</Btn>
        <button onClick={onCancel} style={{ background: 'none', color: 'var(--text-muted)', fontSize: 12, padding: '4px 8px' }}>
          Cancel
        </button>
        {error && <span style={{ fontSize: 12, color: 'var(--danger)' }}>{error}</span>}
      </div>
    </div>
  )
}

function TradeRow({ trade, myNationId, onAction }) {
  const isIncoming = trade.to_nation_id === myNationId
  const isFrom     = trade.from_nation_id === myNationId
  const other      = isIncoming ? trade.from_nation_name : trade.to_nation_name
  const [acting, setActing]     = useState(false)
  const [err, setErr]           = useState('')
  const [editing, setEditing]   = useState(false)
  const [localTrade, setLocal]  = useState(trade)

  // Keep local copy in sync when parent reloads
  useEffect(() => { setLocal(trade) }, [trade])

  const myAcceptedAt  = isFrom ? localTrade.from_accepted_at  : localTrade.to_accepted_at
  const myConfirmedAt = isFrom ? localTrade.from_confirmed_at : localTrade.to_confirmed_at
  const theirAcceptedAt  = isFrom ? localTrade.to_accepted_at    : localTrade.from_accepted_at
  const theirConfirmedAt = isFrom ? localTrade.to_confirmed_at   : localTrade.from_confirmed_at

  const act = async (endpoint) => {
    setActing(true)
    setErr('')
    const r = await fetch(`/api/trade/${localTrade.id}/${endpoint}`, {
      method: 'POST',
      credentials: 'include',
    })
    const data = await r.json()
    if (!r.ok) setErr(data.detail || 'Action failed')
    else {
      if (data.status !== 'pending') onAction()
      else setLocal(data)
    }
    setActing(false)
  }

  return (
    <Tr>
      <Td>
        <span style={{ fontSize: 12, color: isIncoming ? 'var(--teal)' : 'var(--text-muted)' }}>
          {isIncoming ? '← incoming' : '→ outgoing'}
        </span>
      </Td>
      <Td style={{ fontWeight: 500 }}>{other}</Td>
      <Td>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <ResourceLine label="offers:" minerals={localTrade.offer_minerals} fuel={localTrade.offer_fuel} currency={localTrade.offer_currency} />
          <ResourceLine label="wants:"  minerals={localTrade.request_minerals} fuel={localTrade.request_fuel} currency={localTrade.request_currency} />
          {localTrade.offer_probe_data?.length > 0 && (
          <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>probe data ({localTrade.offer_probe_data.length} planet{localTrade.offer_probe_data.length !== 1 ? 's' : ''}):</span>
            {localTrade.offer_probe_data.map((pd, i) => (
              <span key={i} style={{ fontSize: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ color: 'var(--amber)' }}>{Number(pd.mineral_richness).toFixed(1)}M</span>
                <span style={{ color: 'var(--teal)' }}>{Number(pd.fuel_richness).toFixed(1)}F</span>
                {pd.territory_type === 'anomaly' && <span style={{ color: 'var(--amber)', fontSize: 10 }}>anomaly</span>}
                {'is_reachable' in pd && (
                  <span style={{ fontSize: 10, color: pd.is_reachable ? 'var(--teal)' : 'var(--text-muted)' }}>
                    {pd.is_reachable ? '✓ reachable' : '✗ blocked'}
                  </span>
                )}
              </span>
            ))}
          </div>
        )}
        {(localTrade.includes_peace || localTrade.offer_territory_name || localTrade.request_territory_name) && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 2 }}>
              {localTrade.includes_peace && (
                <span style={{ fontSize: 12, color: 'var(--teal)', fontWeight: 600 }}>Peace</span>
              )}
              {localTrade.offer_territory_name && (
                <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                  <span style={{ color: 'var(--text-muted)', marginRight: 4 }}>offers territory:</span>
                  {localTrade.offer_territory_name}
                </span>
              )}
              {localTrade.request_territory_name && (
                <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                  <span style={{ color: 'var(--text-muted)', marginRight: 4 }}>wants territory:</span>
                  {localTrade.request_territory_name}
                </span>
              )}
            </div>
          )}
        </div>
        {editing && (
          <EditTradeForm
            trade={localTrade}
            onEdited={updated => { setLocal(updated); setEditing(false) }}
            onCancel={() => setEditing(false)}
          />
        )}
      </Td>
      <Td>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {/* Confirmation row */}
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <ConfirmButton
              label="Accept"
              acceptedAt={myAcceptedAt}
              confirmedAt={myConfirmedAt}
              onAccept={() => act('accept')}
              disabled={acting}
              color={isFrom ? 'amber' : 'green'}
            />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                Their side: {theirConfirmedAt ? (
                  <span style={{ color: 'var(--teal)' }}>confirmed</span>
                ) : theirAcceptedAt ? (
                  <span style={{ color: 'var(--amber)' }}>accepted</span>
                ) : (
                  <span>pending</span>
                )}
              </span>
            </div>
          </div>

          {/* Action buttons */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <button
              onClick={() => setEditing(e => !e)}
              style={{
                padding: '3px 8px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border)',
                background: 'transparent',
                color: 'var(--text-muted)',
                fontSize: 11,
                cursor: 'pointer',
              }}
            >
              {editing ? 'Close edit' : 'Edit terms'}
            </button>
            {isIncoming ? (
              <button
                onClick={() => act('reject')}
                disabled={acting}
                style={{
                  padding: '3px 8px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border)',
                  background: 'transparent',
                  color: 'var(--text-muted)',
                  fontSize: 11,
                  cursor: acting ? 'not-allowed' : 'pointer',
                }}
              >
                Reject
              </button>
            ) : (
              <button
                onClick={() => act('cancel')}
                disabled={acting}
                style={{
                  padding: '3px 8px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border)',
                  background: 'transparent',
                  color: 'var(--text-muted)',
                  fontSize: 11,
                  cursor: acting ? 'not-allowed' : 'pointer',
                }}
              >
                Cancel
              </button>
            )}
          </div>
          {err && <span style={{ fontSize: 11, color: 'var(--danger)' }}>{err}</span>}
        </div>
      </Td>
    </Tr>
  )
}

export default function Trade() {
  const { nation } = useNation()
  const [nations, setNations] = useState([])
  const [trades, setTrades]   = useState([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    const [nRes, tRes] = await Promise.all([
      fetch('/api/nations/list', { credentials: 'include' }),
      fetch('/api/trade',       { credentials: 'include' }),
    ])
    if (nRes.ok) setNations(await nRes.json())
    if (tRes.ok) setTrades(await tRes.json())
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div style={{ padding: 40, color: 'var(--text-muted)' }}>Loading…</div>

  const incoming = trades.filter(t => t.to_nation_id === nation?.id)
  const outgoing = trades.filter(t => t.from_nation_id === nation?.id)

  return (
    <div>
      <PageHeader title="Trade" sub="Propose and manage resource exchanges with other nations." />

      <ProposeForm nations={nations} myNation={nation} onProposed={load} />

      {incoming.length > 0 && (
        <>
          <SectionLabel>Incoming Offers</SectionLabel>
          <Card style={{ padding: 0, marginBottom: 24 }}>
            <Table headers={['', 'From', 'Terms', 'Actions']}>
              {incoming.map(t => (
                <TradeRow key={t.id} trade={t} myNationId={nation?.id} onAction={load} />
              ))}
            </Table>
          </Card>
        </>
      )}

      <SectionLabel>Outgoing Offers</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['', 'To', 'Terms', '']}>
          {outgoing.length === 0 ? (
            <Tr>
              <Td colSpan={4} style={{ textAlign: 'center', padding: '40px 0' }}>
                <EmptyState title="No outgoing offers" body="Propose a trade above to start." />
              </Td>
            </Tr>
          ) : outgoing.map(t => (
            <TradeRow key={t.id} trade={t} myNationId={nation?.id} onAction={load} />
          ))}
        </Table>
      </Card>
    </div>
  )
}
