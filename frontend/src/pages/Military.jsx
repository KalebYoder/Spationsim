import { PageHeader, Card, SectionLabel, EmptyState, Table, Tr, Td, Badge, Btn, AlertBanner } from '../components/ui'

export default function Military() {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600 }}>Military</h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
            Fleet management, confirmation windows, and active wars
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <Btn variant="ghost" disabled>Declare War</Btn>
          <Btn variant="amber" disabled>Launch Fleet</Btn>
        </div>
      </div>

      {/* Confirmation windows — most critical section */}
      <SectionLabel>Confirmation Windows</SectionLabel>
      <Card>
        <EmptyState
          title="No pending confirmations"
          body="Fleets arriving at your territories will appear here. You have 4 hours (2 ticks) to confirm or recall before standing orders execute."
        />
      </Card>

      {/* Incoming threats */}
      <SectionLabel>Incoming Fleets</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['Nation', 'Fleet Size', 'Destination', 'ETA', 'Window Expires', 'Action']}>
          <Tr>
            <Td colSpan={6} style={{ textAlign: 'center', padding: '40px 0' }}>
              <EmptyState title="No incoming fleets" />
            </Td>
          </Tr>
        </Table>
      </Card>

      {/* Your fleets */}
      <SectionLabel>Your Fleets</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['Fleet', 'Units', 'Status', 'Origin', 'Destination', 'ETA', 'Standing Order', 'Actions']}>
          <Tr>
            <Td colSpan={8} style={{ textAlign: 'center', padding: '40px 0' }}>
              <EmptyState
                title="No fleets"
                body="Build military units and launch fleets from your territories."
              />
            </Td>
          </Tr>
        </Table>
      </Card>

      {/* Active wars */}
      <SectionLabel>Active Wars</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['Nation', 'Declared', 'Status', 'Your Losses', 'Their Losses', 'Actions']}>
          <Tr>
            <Td colSpan={6} style={{ textAlign: 'center', padding: '40px 0' }}>
              <EmptyState title="No active wars" />
            </Td>
          </Tr>
        </Table>
      </Card>
    </div>
  )
}
