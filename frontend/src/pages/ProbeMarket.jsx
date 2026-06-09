import { useState, useEffect, useCallback } from 'react'
import { useNation } from '../hooks/useNation'
import { Card, SectionLabel, EmptyState, Badge, Btn } from '../components/ui'

const SORT_OPTIONS = [
  { value: 'total_richness', label: 'Total Richness' },
  { value: 'mineral_richness', label: 'Mineral Richness' },
  { value: 'fuel_richness', label: 'Fuel Richness' },
  { value: 'price', label: 'Price' },
  { value: 'listed_at', label: 'Date Listed' },
]

function RichnessBar({ value, max = 10, color }) {
  const pct = Math.min(100, (value / max) * 100)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: 'var(--bg-hover)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3, transition: 'width 0.2s' }} />
      </div>
      <span style={{ fontSize: 12, color, fontVariantNumeric: 'tabular-nums', minWidth: 28, textAlign: 'right' }}>
        {value.toFixed(1)}
      </span>
    </div>
  )
}

function ListingCard({ listing, myNationId, onBuy, onDelist }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  const total = listing.mineral_richness + listing.fuel_richness
  const age = (() => {
    const ms = Date.now() - new Date(listing.listed_at).getTime()
    const h = Math.floor(ms / 3_600_000)
    if (h < 24) return `${h}h ago`
    return `${Math.floor(h / 24)}d ago`
  })()

  const handleBuy = async () => {
    setBusy(true)
    await onBuy(listing.id)
    setBusy(false)
    setConfirming(false)
  }

  const handleDelist = async () => {
    setBusy(true)
    await onDelist(listing.id)
    setBusy(false)
  }

  return (
    <Card style={{ position: 'relative' }}>
      {/* Top row: badges + price */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {listing.is_own && <Badge color="teal">Your Listing</Badge>}
          {listing.already_have && !listing.is_own && <Badge color="amber">Already Owned</Badge>}
          {listing.is_owned && (
            <Badge color="rose">
              {listing.colonized_by_name ? `Colonized by ${listing.colonized_by_name}` : 'Colonized'}
            </Badge>
          )}
          {listing.is_reachable === true && <Badge color="teal">Reachable</Badge>}
          {listing.is_reachable === false && <Badge color="neutral">Blocked</Badge>}
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 12 }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--amber)' }}>
            {Number(listing.price).toLocaleString()}¤
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{age}</div>
        </div>
      </div>

      {/* Seller */}
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
        Seller: <span style={{ color: 'var(--text-secondary)' }}>{listing.seller_nation_name}</span>
        {listing.node_key && (
          <span style={{ marginLeft: 8, color: 'var(--text-muted)' }}>· {listing.node_key}</span>
        )}
      </div>

      {/* Richness bars */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', width: 56, flexShrink: 0 }}>Minerals</span>
          <RichnessBar value={listing.mineral_richness} color="var(--amber)" />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', width: 56, flexShrink: 0 }}>Fuel</span>
          <RichnessBar value={listing.fuel_richness} color="var(--teal)" />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', width: 56, flexShrink: 0 }}>Total</span>
          <RichnessBar value={total} max={20} color="var(--text-secondary)" />
        </div>
      </div>

      {/* Actions */}
      {listing.is_own ? (
        <Btn
          variant="ghost"
          onClick={handleDelist}
          disabled={busy}
          style={{ width: '100%', fontSize: 12 }}
        >
          {busy ? 'Delisting…' : 'Delist'}
        </Btn>
      ) : listing.already_have ? (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'center', paddingTop: 4 }}>
          You already have this data
        </div>
      ) : confirming ? (
        <div style={{ display: 'flex', gap: 8 }}>
          <Btn onClick={() => setConfirming(false)} style={{ flex: 1, fontSize: 12 }}>Cancel</Btn>
          <Btn
            variant="amber"
            onClick={handleBuy}
            disabled={busy}
            style={{ flex: 1, fontSize: 12 }}
          >
            {busy ? 'Buying…' : `Confirm — ${Number(listing.price).toLocaleString()}¤`}
          </Btn>
        </div>
      ) : (
        <Btn
          variant="amber"
          onClick={() => setConfirming(true)}
          style={{ width: '100%', fontSize: 12 }}
        >
          Buy Probe Data
        </Btn>
      )}
    </Card>
  )
}

// ── My Listings panel ──────────────────────────────────────────────────────

function MyListingsPanel({ myData, listings, onList, onDelist }) {
  const [selectedId, setSelectedId] = useState('')
  const [price, setPrice] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const listedIds = new Set(listings.filter(l => l.is_own).map(l => l.probe_data_id))
  const available = myData.filter(d => !listedIds.has(d.id))

  const handleList = async () => {
    if (!selectedId || !price) return
    setBusy(true)
    setError('')
    const err = await onList(parseInt(selectedId), parseFloat(price))
    if (err) setError(err)
    else { setSelectedId(''); setPrice('') }
    setBusy(false)
  }

  return (
    <Card>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12 }}>List Probe Data for Sale</div>
      {available.length === 0 ? (
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          All your probe data is already listed, or you have none to sell.
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div style={{ flex: '1 1 200px' }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Probe data</div>
            <select
              value={selectedId}
              onChange={e => setSelectedId(e.target.value)}
              style={{ width: '100%', padding: '6px 8px', fontSize: 13, background: 'var(--bg-surface)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}
            >
              <option value="">Select territory…</option>
              {available.map(d => (
                <option key={d.id} value={d.id}>
                  {d.territory_name || d.node_key} — Min {d.mineral_richness.toFixed(1)} / Fuel {d.fuel_richness.toFixed(1)}
                  {d.is_owned ? ' (owned)' : ''}
                </option>
              ))}
            </select>
          </div>
          <div style={{ flex: '0 1 120px' }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Price (¤)</div>
            <input
              type="number"
              min="1"
              value={price}
              onChange={e => setPrice(e.target.value)}
              placeholder="e.g. 5000"
              style={{ width: '100%', padding: '6px 8px', fontSize: 13, background: 'var(--bg-surface)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}
            />
          </div>
          <Btn variant="amber" onClick={handleList} disabled={busy || !selectedId || !price}>
            {busy ? 'Listing…' : 'List'}
          </Btn>
        </div>
      )}
      {error && <div style={{ color: 'var(--danger)', fontSize: 12, marginTop: 8 }}>{error}</div>}
    </Card>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function ProbeMarket() {
  const { nation } = useNation()
  const [listings, setListings] = useState([])
  const [myData, setMyData] = useState([])
  const [sort, setSort] = useState('total_richness')
  const [order, setOrder] = useState('desc')
  const [reachableOnly, setReachableOnly] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ sort, order, reachable_only: reachableOnly })
      const [mRes, dRes] = await Promise.all([
        fetch(`/api/probe-market?${params}`, { credentials: 'include' }),
        fetch('/api/probes/data', { credentials: 'include' }),
      ])
      if (mRes.ok) setListings(await mRes.json())
      if (dRes.ok) setMyData(await dRes.json())
    } catch {
      setError('Failed to load marketplace')
    }
    setLoading(false)
  }, [sort, order, reachableOnly])

  useEffect(() => { load() }, [load])

  const handleList = async (probeDataId, price) => {
    const r = await fetch('/api/probe-market', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ probe_data_id: probeDataId, price }),
    })
    if (!r.ok) {
      const d = await r.json()
      return d.detail || 'Failed to list'
    }
    await load()
    return null
  }

  const handleDelist = async (listingId) => {
    await fetch(`/api/probe-market/${listingId}`, { method: 'DELETE', credentials: 'include' })
    await load()
  }

  const handleBuy = async (listingId) => {
    const r = await fetch(`/api/probe-market/${listingId}/buy`, { method: 'POST', credentials: 'include' })
    if (!r.ok) {
      const d = await r.json()
      setError(d.detail || 'Purchase failed')
      return
    }
    await load()
  }

  if (loading) return <p style={{ color: 'var(--text-muted)' }}>Loading…</p>

  const ownListings = listings.filter(l => l.is_own)
  const otherListings = listings.filter(l => !l.is_own)

  return (
    <div>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 22, fontWeight: 600 }}>Probe Data Market</h1>
        <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
          Buy and sell territory scan data. Richness is shown before purchase; coordinates revealed after.
        </p>
      </div>

      {error && (
        <div style={{ color: 'var(--danger)', fontSize: 13, marginBottom: 16, padding: '8px 12px', background: 'rgba(192,114,106,0.08)', borderRadius: 'var(--radius-sm)', border: '1px solid rgba(192,114,106,0.2)' }}>
          {error}
          <button onClick={() => setError('')} style={{ marginLeft: 12, fontSize: 11, color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer' }}>Dismiss</button>
        </div>
      )}

      <MyListingsPanel myData={myData} listings={listings} onList={handleList} onDelist={handleDelist} />

      {/* Controls */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', margin: '20px 0 16px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Sort</span>
          <select
            value={sort}
            onChange={e => setSort(e.target.value)}
            style={{ padding: '5px 8px', fontSize: 13, background: 'var(--bg-surface)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}
          >
            {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <button
            onClick={() => setOrder(o => o === 'desc' ? 'asc' : 'desc')}
            style={{ padding: '5px 10px', fontSize: 12, background: 'var(--bg-surface)', color: 'var(--text-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}
          >
            {order === 'desc' ? '↓ High → Low' : '↑ Low → High'}
          </button>
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--text-secondary)', cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={reachableOnly}
            onChange={e => setReachableOnly(e.target.checked)}
          />
          Reachable territories only
        </label>
        <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 'auto' }}>
          {otherListings.length} listing{otherListings.length !== 1 ? 's' : ''}
        </span>
      </div>

      {ownListings.length > 0 && (
        <>
          <SectionLabel>Your Listings</SectionLabel>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12, marginBottom: 24 }}>
            {ownListings.map(l => (
              <ListingCard key={l.id} listing={l} myNationId={nation?.id} onBuy={handleBuy} onDelist={handleDelist} />
            ))}
          </div>
        </>
      )}

      <SectionLabel>Available Listings</SectionLabel>
      {otherListings.length === 0 ? (
        <Card>
          <EmptyState title="No listings" body={reachableOnly ? 'No reachable listings found. Try disabling the reachability filter.' : 'No probe data is currently for sale.'} />
        </Card>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
          {otherListings.map(l => (
            <ListingCard key={l.id} listing={l} myNationId={nation?.id} onBuy={handleBuy} onDelist={handleDelist} />
          ))}
        </div>
      )}
    </div>
  )
}
