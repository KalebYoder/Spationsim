import { useState } from 'react'
import { useNation } from '../hooks/useNation'
import { PageHeader, Card, SectionLabel, EmptyState, Badge, Btn } from '../components/ui'

function TerritoryCard({ territory, flagColor }) {
  const [open, setOpen] = useState(false)

  return (
    <Card style={{ padding: 0, overflow: 'hidden' }}>
      {/* Header */}
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '14px 20px',
          cursor: 'pointer',
          background: open ? 'var(--bg-hover)' : 'transparent',
          borderBottom: open ? '1px solid var(--border)' : 'none',
          transition: 'background 0.15s',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{
            display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
            background: flagColor || 'var(--teal)',
          }} />
          <span style={{ fontWeight: 500 }}>{territory.node_key}</span>
          <Badge color="teal">Home</Badge>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 13, color: 'var(--text-secondary)' }}>
          <span>Distance {territory.distance_from_center}</span>
          <span>Min {territory.mineral_richness?.toFixed(2)}</span>
          <span>Fuel {territory.fuel_richness?.toFixed(2)}</span>
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{open ? '▲' : '▼'}</span>
        </div>
      </div>

      {/* Expanded detail */}
      {open && (
        <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 20 }}>
          <div>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 8 }}>
              Population
            </div>
            <EmptyState title="—" body="No population data yet" />
          </div>
          <div>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 8 }}>
              Facilities
            </div>
            <EmptyState title="None built" body="Build facilities from the Facilities page" />
          </div>
          <div>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 8 }}>
              Stationed Military
            </div>
            <EmptyState title="None" body="Station fleets from the Military page" />
          </div>
        </div>
      )}
    </Card>
  )
}

export default function Planets() {
  const { nation, loading } = useNation()
  const [homeTerritory, setHomeTerritory] = useState(null)
  const [fetched, setFetched] = useState(false)

  if (!fetched && nation?.home_territory_id) {
    setFetched(true)
    fetch(`/api/territories/available`, { credentials: 'include' })
      .then(r => r.json())
      .then(() => {
        // Placeholder: full territory endpoint coming in Phase 2
        setHomeTerritory({ node_key: '(home)', distance_from_center: '?', mineral_richness: null, fuel_richness: null })
      })
  }

  if (loading) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600 }}>Planets</h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
            Per-territory breakdown of population, facilities, and military
          </p>
        </div>
        <Btn variant="amber" disabled>Send Colony Ship</Btn>
      </div>

      <SectionLabel>Your Territories</SectionLabel>

      {nation ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {homeTerritory && (
            <TerritoryCard territory={homeTerritory} flagColor={nation.flag_color} />
          )}
          {!homeTerritory && (
            <Card>
              <EmptyState
                title="Territory data loading"
                body="Full per-territory breakdown available once the territory endpoint is complete (Phase 2)."
              />
            </Card>
          )}
        </div>
      ) : (
        <Card>
          <EmptyState title="No territories" body="Create your nation to claim a home system." />
        </Card>
      )}
    </div>
  )
}
