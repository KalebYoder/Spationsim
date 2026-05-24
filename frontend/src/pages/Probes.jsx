import { PageHeader, Card, SectionLabel, EmptyState, Table, Tr, Td, Badge, Btn } from '../components/ui'

export default function Probes() {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600 }}>Probes</h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
            Active probes, discovered system data, and the information marketplace
          </p>
        </div>
        <Btn variant="teal" disabled>Launch Probe</Btn>
      </div>

      {/* In transit */}
      <SectionLabel>In Transit</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['Probe', 'Origin', 'Destination', 'Launched', 'ETA', 'Status']}>
          <Tr>
            <Td colSpan={6} style={{ textAlign: 'center', padding: '40px 0' }}>
              <EmptyState
                title="No probes in transit"
                body="Launch probes from colonized territories to scout uncharted systems."
              />
            </Td>
          </Tr>
        </Table>
      </Card>

      {/* Your intel */}
      <SectionLabel>Your Intelligence</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['System', 'Minerals', 'Fuel', 'Scouted', 'Status', 'Actions']}>
          <Tr>
            <Td colSpan={6} style={{ textAlign: 'center', padding: '40px 0' }}>
              <EmptyState
                title="No probe data yet"
                body="Data collected by your probes will appear here. Data shows resource richness and colonization status at time of scan."
              />
            </Td>
          </Tr>
        </Table>
      </Card>

      {/* Purchased intel */}
      <SectionLabel>Purchased Intelligence</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['System', 'Minerals', 'Fuel', 'Sold By', 'Purchased', 'Data Age', 'Status']}>
          <Tr>
            <Td colSpan={7} style={{ textAlign: 'center', padding: '40px 0' }}>
              <EmptyState
                title="No purchased data"
                body="Probe data bought from other players appears here. Data age and colonization status are shown so you can assess its value."
              />
            </Td>
          </Tr>
        </Table>
      </Card>

      {/* Marketplace */}
      <SectionLabel>Sell Your Data</SectionLabel>
      <Card>
        <EmptyState
          title="No data listed for sale"
          body="List your probe data on the marketplace to sell to other players. You retain the data after sale."
        />
      </Card>
    </div>
  )
}
