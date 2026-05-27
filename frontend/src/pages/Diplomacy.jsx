import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useNation } from '../hooks/useNation'
import { diploColor } from '../hooks/useDiplomacy'
import { PageHeader, Card, SectionLabel, EmptyState, Table, Tr, Td, Badge } from '../components/ui'

const STATUS_COLOR = {
  war:      { label: 'War',      color: '#c0726a' },
  friendly: { label: 'Friendly', color: '#6aab72' },
  neutral:  { label: 'Neutral',  color: '#b8a98a' },
}

export default function Diplomacy() {
  const { nation } = useNation()
  const navigate = useNavigate()
  const [relations, setRelations] = useState([])

  const loadRelations = useCallback(async () => {
    const r = await fetch('/api/diplomacy/relations', { credentials: 'include' })
    if (r.ok) setRelations(await r.json())
  }, [])

  useEffect(() => { loadRelations() }, [loadRelations])

  return (
    <div>
      <PageHeader
        title="Diplomacy"
        sub="Your active diplomatic relationships. Visit a nation's profile to change status."
      />

      <SectionLabel>Active Relationships</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['Nation', 'Status', 'Since']}>
          {relations.length === 0 ? (
            <Tr>
              <Td colSpan={3} style={{ textAlign: 'center', padding: '40px 0' }}>
                <EmptyState title="All nations are neutral" body="Visit a nation's profile to set a relationship." />
              </Td>
            </Tr>
          ) : relations.map(r => {
            const s = STATUS_COLOR[r.status] || STATUS_COLOR.neutral
            return (
              <Tr
                key={r.nation_id}
                onClick={() => navigate(`/nations/${r.nation_id}`)}
                style={{ cursor: 'pointer' }}
              >
                <Td>
                  <span style={{ fontWeight: 500, color: diploColor(r.status) }}>{r.nation_name}</span>
                </Td>
                <Td>
                  <span style={{ color: s.color, fontWeight: 600, fontSize: 13 }}>{s.label}</span>
                </Td>
                <Td style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
                  {new Date(r.updated_at).toLocaleDateString()}
                </Td>
              </Tr>
            )
          })}
        </Table>
      </Card>

      {/* Alliances — post-beta placeholder */}
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
    </div>
  )
}
