import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useNation } from '../hooks/useNation'
import { diploColor } from '../hooks/useDiplomacy'
import { PageHeader, Card, SectionLabel, EmptyState, Table, Tr, Td } from '../components/ui'

export default function FriendsList() {
  const navigate = useNavigate()
  const { nation: myNation } = useNation()
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const r = await fetch('/api/diplomacy/friends', { credentials: 'include' })
    if (r.ok) setEntries(await r.json())
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const act = async (nationId, endpoint) => {
    await fetch(`/api/diplomacy/${nationId}/${endpoint}`, {
      method: 'POST',
      credentials: 'include',
    })
    load()
  }

  const friends  = entries.filter(e => e.status === 'friendly')
  const incoming = entries.filter(e => e.status === 'friend_pending' && e.requested_by !== myNation?.id)
  const outgoing = entries.filter(e => e.status === 'friend_pending' && e.requested_by === myNation?.id)

  if (loading) return <div style={{ padding: 40, color: 'var(--text-muted)' }}>Loading…</div>

  return (
    <div>
      <PageHeader title="Friends" sub="Accepted friends and pending requests." />

      {incoming.length > 0 && (
        <>
          <SectionLabel>Incoming Requests</SectionLabel>
          <Card style={{ padding: 0 }}>
            <Table headers={['Nation', 'Actions']}>
              {incoming.map(e => (
                <Tr key={e.nation_id}>
                  <Td>
                    <span
                      style={{ fontWeight: 500, cursor: 'pointer', color: diploColor(e.status) }}
                      onClick={() => navigate(`/nations/${e.nation_id}`)}
                    >
                      {e.nation_name}
                    </span>
                  </Td>
                  <Td>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button
                        onClick={() => act(e.nation_id, 'accept-friend')}
                        style={{
                          padding: '5px 12px',
                          borderRadius: 'var(--radius-sm)',
                          border: '1px solid #2a4e30',
                          background: '#152318',
                          color: '#5a8a62',
                          fontSize: 13, fontWeight: 600,
                          cursor: 'pointer',
                        }}
                      >
                        Accept
                      </button>
                      <button
                        onClick={() => act(e.nation_id, 'refuse-friend')}
                        style={{
                          padding: '5px 12px',
                          borderRadius: 'var(--radius-sm)',
                          border: '1px solid var(--border)',
                          background: 'transparent',
                          color: 'var(--text-muted)',
                          fontSize: 13,
                          cursor: 'pointer',
                        }}
                      >
                        Refuse
                      </button>
                    </div>
                  </Td>
                </Tr>
              ))}
            </Table>
          </Card>
        </>
      )}

      {outgoing.length > 0 && (
        <>
          <SectionLabel>Sent Requests</SectionLabel>
          <Card style={{ padding: 0 }}>
            <Table headers={['Nation', '']}>
              {outgoing.map(e => (
                <Tr key={e.nation_id}>
                  <Td>
                    <span
                      style={{ fontWeight: 500, cursor: 'pointer', color: diploColor(e.status) }}
                      onClick={() => navigate(`/nations/${e.nation_id}`)}
                    >
                      {e.nation_name}
                    </span>
                  </Td>
                  <Td style={{ textAlign: 'right' }}>
                    <button
                      onClick={() => act(e.nation_id, 'refuse-friend')}
                      style={{
                        padding: '4px 10px',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border)',
                        background: 'transparent',
                        color: 'var(--text-muted)',
                        fontSize: 12,
                        cursor: 'pointer',
                      }}
                    >
                      Cancel
                    </button>
                  </Td>
                </Tr>
              ))}
            </Table>
          </Card>
        </>
      )}

      <SectionLabel>Friends</SectionLabel>
      <Card style={{ padding: 0 }}>
        <Table headers={['Nation', 'Since', '']}>
          {friends.length === 0 ? (
            <Tr>
              <Td colSpan={3} style={{ textAlign: 'center', padding: '40px 0' }}>
                <EmptyState title="No friends yet" body="Visit a nation's profile to send a friend request." />
              </Td>
            </Tr>
          ) : friends.map(e => (
            <Tr key={e.nation_id}>
              <Td>
                <span
                  style={{ fontWeight: 500, cursor: 'pointer', color: diploColor(e.status) }}
                  onClick={() => navigate(`/nations/${e.nation_id}`)}
                >
                  {e.nation_name}
                </span>
              </Td>
              <Td style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
                {new Date(e.updated_at).toLocaleDateString()}
              </Td>
              <Td style={{ textAlign: 'right' }}>
                <button
                  onClick={() => act(e.nation_id, 'remove-friend')}
                  style={{
                    padding: '4px 10px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border)',
                    background: 'transparent',
                    color: 'var(--text-muted)',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                >
                  Remove
                </button>
              </Td>
            </Tr>
          ))}
        </Table>
      </Card>
    </div>
  )
}
