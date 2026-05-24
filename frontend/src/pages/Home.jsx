import { useAuth } from '../context/AuthContext'
import { useNation } from '../hooks/useNation'
import { PageHeader, StatCard, Card, SectionLabel, AlertBanner, EmptyState } from '../components/ui'

const fmt = n => Number(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })

export default function Home() {
  const { player } = useAuth()
  const { nation, loading } = useNation()

  if (loading) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  return (
    <div>
      <PageHeader
        title={nation ? nation.name : `Welcome, ${player?.username}`}
        sub={nation ? `Currency: ${nation.currency_name}` : undefined}
      />

      {/* Active alerts */}
      <SectionLabel>Active Alerts</SectionLabel>
      <Card style={{ marginBottom: 0 }}>
        <EmptyState
          title="No active alerts"
          body="Confirmation windows, incoming fleets, and war declarations will appear here."
        />
      </Card>

      {/* Resource summary */}
      <SectionLabel>Resources</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 14 }}>
        <StatCard
          label="Minerals"
          value={fmt(nation?.minerals)}
          sub="per tick: —"
          accent="var(--amber)"
        />
        <StatCard
          label="Fuel"
          value={fmt(nation?.fuel)}
          sub="per tick: —"
          accent="var(--teal)"
        />
        <StatCard
          label="Population"
          value="—"
          sub="unassigned: —"
          accent="var(--purple)"
        />
        <StatCard label="Territories" value="—" />
        <StatCard label="Military" value="—" sub="units" />
      </div>

      {/* Event feed */}
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
