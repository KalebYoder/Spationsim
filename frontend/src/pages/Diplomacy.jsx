import { useState } from 'react'
import { PageHeader, Card, SectionLabel, EmptyState, Table, Tr, Td, Badge, Btn } from '../components/ui'

const STATUS_COLORS = { allied: 'teal', neutral: 'muted', hostile: 'danger', war: 'danger' }

export default function Diplomacy() {
  const [defaultStance, setDefaultStance] = useState('neutral')

  return (
    <div>
      <PageHeader
        title="Diplomacy"
        sub="Relationships, war declarations, and standing diplomatic status"
      />

      {/* Default stance */}
      <SectionLabel>Default Stance</SectionLabel>
      <Card style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontWeight: 500, marginBottom: 4 }}>Default diplomatic status for new nations</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
            Applied to any nation you have no explicit relationship with
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {['neutral', 'hostile'].map(stance => (
            <button
              key={stance}
              onClick={() => setDefaultStance(stance)}
              style={{
                padding: '6px 14px',
                borderRadius: 'var(--radius-sm)',
                border: `1px solid ${defaultStance === stance ? 'var(--amber)' : 'var(--border)'}`,
                background: defaultStance === stance ? 'var(--amber-dim)' : 'transparent',
                color: defaultStance === stance ? 'var(--amber)' : 'var(--text-secondary)',
                fontSize: 13,
                cursor: 'pointer',
                textTransform: 'capitalize',
              }}
            >
              {stance}
            </button>
          ))}
        </div>
      </Card>

      {/* Active wars */}
      <SectionLabel>Active Wars</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['Nation', 'Declared', 'Aggressor', 'Duration', 'Resource Drain', 'Actions']}>
          <Tr>
            <Td colSpan={6} style={{ textAlign: 'center', padding: '40px 0' }}>
              <EmptyState title="No active wars" />
            </Td>
          </Tr>
        </Table>
      </Card>

      {/* Explicit relationships */}
      <SectionLabel>Diplomatic Relationships</SectionLabel>
      <Card style={{ padding: 0 }}>
        <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end' }}>
          <Btn variant="ghost" disabled>Set Status</Btn>
        </div>
        <Table headers={['Nation', 'Status', 'Updated', 'Actions']}>
          <Tr>
            <Td colSpan={4} style={{ textAlign: 'center', padding: '40px 0' }}>
              <EmptyState
                title="No explicit relationships"
                body="All nations default to your default stance unless overridden here."
              />
            </Td>
          </Tr>
        </Table>
      </Card>

      {/* Alliance section — placeholder for post-beta */}
      <SectionLabel>Alliances</SectionLabel>
      <Card style={{ opacity: 0.5 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontWeight: 500, marginBottom: 4 }}>Alliance Management</div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
              Formal alliances, shared banks, and coordinated war mechanics — coming post-beta.
              Players organize via Discord during closed beta.
            </div>
          </div>
          <Badge color="muted">Post-Beta</Badge>
        </div>
      </Card>

      {/* War declaration */}
      <SectionLabel>Declare War</SectionLabel>
      <Card>
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontWeight: 500, marginBottom: 6 }}>War requires a formal declaration</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
            Declaring war enables fleet combat against the target nation. The target nation is notified immediately.
            Fleets still require a 4-hour confirmation window on arrival — no instant strikes.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <input
            type="text"
            placeholder="Nation name&hellip;"
            disabled
            style={{
              flex: 1,
              padding: '8px 12px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border)',
              background: 'var(--bg-surface)',
              color: 'var(--text-primary)',
            }}
          />
          <Btn variant="danger" disabled>Declare War</Btn>
        </div>
      </Card>
    </div>
  )
}
