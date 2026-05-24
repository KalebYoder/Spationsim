import { useState, useEffect, useCallback } from 'react'
import { Card, SectionLabel, EmptyState, Table, Tr, Td, Btn, StatCard } from '../components/ui'

function ManufactureForm({ stats, onManufactured, onCancel }) {
  const [quantity, setQuantity] = useState(1)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const mineralCost = stats.manufacture_cost_minerals * quantity
  const fuelCost = stats.manufacture_cost_fuel * quantity

  const handleBuild = async () => {
    setSubmitting(true)
    setError('')
    try {
      const r = await fetch('/api/probes/manufacture', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quantity }),
      })
      const data = await r.json()
      if (!r.ok) { setError(data.detail || 'Failed'); return }
      onManufactured(data)
    } catch {
      setError('Network error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card style={{ marginBottom: 24 }}>
      <div style={{ marginBottom: 12, fontWeight: 500 }}>
        Manufacture Probes
        <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 12 }}>
          {stats.nodes_per_tick} node{stats.nodes_per_tick !== 1 ? 's' : ''} per tick
        </span>
      </div>
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Quantity</div>
          <input
            type="number"
            min={1}
            value={quantity}
            onChange={e => setQuantity(Math.max(1, parseInt(e.target.value) || 1))}
            style={{ width: 80, padding: '6px 10px', background: 'var(--bg-base)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}
          />
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', paddingBottom: 2 }}>
          Cost: {mineralCost} minerals, {fuelCost} fuel
        </div>
        <div style={{ display: 'flex', gap: 8, paddingBottom: 2 }}>
          <Btn variant="amber" onClick={handleBuild} disabled={submitting}>{submitting ? 'Building…' : 'Manufacture'}</Btn>
          <Btn variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Btn>
        </div>
      </div>
      {error && <p style={{ color: 'var(--danger)', fontSize: 13, marginTop: 10 }}>{error}</p>}
    </Card>
  )
}

export default function Probes() {
  const [stats, setStats] = useState(null)
  const [nation, setNation] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showManufacture, setShowManufacture] = useState(false)

  const load = useCallback(async () => {
    try {
      const [sRes, nRes] = await Promise.all([
        fetch('/api/probes/stats', { credentials: 'include' }),
        fetch('/api/nations/mine', { credentials: 'include' }),
      ])
      const [s, n] = await Promise.all([sRes.json(), nRes.json()])
      setStats(s)
      setNation(n)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleManufactured = updatedNation => {
    setNation(updatedNation)
    setShowManufacture(false)
    load()
  }

  if (loading) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600 }}>Probes</h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
            Active probes, discovered system data, and the information marketplace
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          {!showManufacture && (
            <Btn variant="ghost" onClick={() => setShowManufacture(true)}>Manufacture Probes</Btn>
          )}
          <Btn variant="teal" disabled>Launch Probe</Btn>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 14, marginBottom: 28 }}>
        <StatCard label="Probes in Reserve" value={stats?.reserve ?? '—'} accent="var(--teal)" />
        <StatCard label="Minerals" value={nation ? parseFloat(nation.minerals).toFixed(0) : '—'} accent="var(--amber)" />
        <StatCard label="Fuel" value={nation ? parseFloat(nation.fuel).toFixed(0) : '—'} accent="var(--teal)" />
      </div>

      {showManufacture && stats && (
        <ManufactureForm
          stats={stats}
          onManufactured={handleManufactured}
          onCancel={() => setShowManufacture(false)}
        />
      )}

      <SectionLabel>In Transit</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['Probe', 'Origin', 'Destination', 'Launched', 'ETA', 'Status']}>
          <Tr>
            <Td colSpan={6} style={{ textAlign: 'center', padding: '40px 0' }}>
              <EmptyState title="No probes in transit" body="Launch probes from colonized territories to scout uncharted systems." />
            </Td>
          </Tr>
        </Table>
      </Card>

      <SectionLabel>Your Intelligence</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['System', 'Minerals', 'Fuel', 'Scouted', 'Status', 'Actions']}>
          <Tr>
            <Td colSpan={6} style={{ textAlign: 'center', padding: '40px 0' }}>
              <EmptyState title="No probe data yet" body="Data collected by your probes will appear here. Data shows resource richness and colonization status at time of scan." />
            </Td>
          </Tr>
        </Table>
      </Card>

      <SectionLabel>Purchased Intelligence</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['System', 'Minerals', 'Fuel', 'Sold By', 'Purchased', 'Data Age', 'Status']}>
          <Tr>
            <Td colSpan={7} style={{ textAlign: 'center', padding: '40px 0' }}>
              <EmptyState title="No purchased data" body="Probe data bought from other players appears here. Data age and colonization status are shown so you can assess its value." />
            </Td>
          </Tr>
        </Table>
      </Card>

      <SectionLabel>Sell Your Data</SectionLabel>
      <Card>
        <EmptyState title="No data listed for sale" body="List your probe data on the marketplace to sell to other players. You retain the data after sale." />
      </Card>
    </div>
  )
}
