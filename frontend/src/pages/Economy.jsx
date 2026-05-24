import { useNation } from '../hooks/useNation'
import { PageHeader, StatCard, Card, SectionLabel, EmptyState, Table, Tr, Td } from '../components/ui'

const fmt = n => Number(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })

export default function Economy() {
  const { nation, loading } = useNation()

  if (loading) return <p style={{ color: 'var(--text-muted)' }}>Loading&hellip;</p>

  return (
    <div>
      <PageHeader
        title="Economy"
        sub="Resource stockpiles, per-tick production, and population overview"
      />

      {/* Stockpiles */}
      <SectionLabel>Stockpiles</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14 }}>
        <StatCard
          label="Minerals"
          value={fmt(nation?.minerals)}
          sub="Net per tick: — (tick system not yet active)"
          accent="var(--amber)"
        />
        <StatCard
          label="Fuel"
          value={fmt(nation?.fuel)}
          sub="Net per tick: — (tick system not yet active)"
          accent="var(--teal)"
        />
      </div>

      {/* Population */}
      <SectionLabel>Population</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14 }}>
        <StatCard label="Total Population" value="—" accent="var(--purple)" />
        <StatCard label="Assigned" value="—" sub="staffing infrastructure" />
        <StatCard label="Unassigned" value="—" sub="available to assign" accent="var(--teal)" />
      </div>

      {/* Per-territory breakdown */}
      <SectionLabel>Production by Territory</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['Territory', 'Minerals / tick', 'Fuel / tick', 'Population', 'Distance']}>
          <Tr>
            <Td colSpan={5} style={{ textAlign: 'center', padding: '48px 0' }}>
              <EmptyState
                title="No production data"
                body="Production breakdown will populate once the tick system is active (Phase 2)."
              />
            </Td>
          </Tr>
        </Table>
      </Card>

      {/* Per-tick spending */}
      <SectionLabel>Spending</SectionLabel>
      <Card>
        <EmptyState
          title="No active spending"
          body="Fleet upkeep and infrastructure maintenance costs will appear here."
        />
      </Card>
    </div>
  )
}
