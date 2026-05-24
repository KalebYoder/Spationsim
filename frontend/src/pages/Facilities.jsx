import { PageHeader, Card, SectionLabel, EmptyState, Table, Tr, Td, Badge, Btn } from '../components/ui'

export default function Facilities() {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600 }}>Facilities</h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
            All infrastructure across your empire
          </p>
        </div>
        <Btn variant="amber" disabled>Build Facility</Btn>
      </div>

      {/* Summary row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 14, marginBottom: 28 }}>
        {['Total Facilities', 'Population Assigned', 'Under Construction'].map(label => (
          <Card key={label} style={{ padding: '16px 20px' }}>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 6 }}>
              {label}
            </div>
            <div style={{ fontSize: 24, fontWeight: 600 }}>—</div>
          </Card>
        ))}
      </div>

      {/* Facility table */}
      <SectionLabel>All Facilities</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['Facility', 'Type', 'Level', 'Territory', 'Population', 'Production', 'Status']}>
          <Tr>
            <Td colSpan={7} style={{ textAlign: 'center', padding: '48px 0' }}>
              <EmptyState
                title="No facilities built"
                body="Build infrastructure on your colonized territories to start generating resources."
              />
            </Td>
          </Tr>
        </Table>
      </Card>
    </div>
  )
}
