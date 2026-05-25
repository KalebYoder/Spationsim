import React, { useState, useEffect, useCallback } from 'react'
import { Card, EmptyState, Btn } from '../components/ui'

const SELECT_STYLE = {
  padding: '7px 10px', background: 'var(--bg-base)', color: 'var(--text-primary)',
  border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', width: '100%',
}
const INPUT_STYLE = {
  padding: '7px 10px', background: 'var(--bg-base)', color: 'var(--text-primary)',
  border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', width: '100%',
  fontFamily: 'inherit',
}
const LABEL_STYLE = {
  fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase',
  letterSpacing: '0.08em', marginBottom: 6, display: 'block',
}
const TH_STYLE = {
  textAlign: 'left', padding: '8px 14px', fontSize: 11, textTransform: 'uppercase',
  letterSpacing: '0.08em', color: 'var(--text-muted)', borderBottom: '1px solid var(--border)',
}

function fmtDate(iso) {
  const d = new Date(iso)
  const now = new Date()
  const diff = now - d
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
  return d.toLocaleDateString()
}

function ComposeForm({ nations, myNation, prefillRecipientId, prefillSubject, onSent, onCancel }) {
  const [recipientId, setRecipientId] = useState(prefillRecipientId ?? '')
  const [subject, setSubject] = useState(prefillSubject ?? '')
  const [body, setBody] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleSend = async () => {
    if (!recipientId || !subject.trim() || !body.trim()) {
      setError('All fields required')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const r = await fetch('/api/mail', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          recipient_nation_id: Number(recipientId),
          subject: subject.trim(),
          body: body.trim(),
        }),
      })
      const data = await r.json()
      if (!r.ok) {
        setError(data.detail || 'Failed to send')
        return
      }
      onSent()
    } catch {
      setError('Network error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card style={{ marginBottom: 20 }}>
      <div style={{ fontWeight: 500, marginBottom: 16 }}>Compose Mail</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <label style={LABEL_STYLE}>To</label>
          <select value={recipientId} onChange={e => setRecipientId(e.target.value)} style={SELECT_STYLE}>
            <option value="">Select nation…</option>
            {nations.filter(n => n.id !== myNation?.id).map(n => (
              <option key={n.id} value={n.id}>{n.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label style={LABEL_STYLE}>Subject</label>
          <input
            value={subject}
            onChange={e => setSubject(e.target.value)}
            style={INPUT_STYLE}
            maxLength={256}
          />
        </div>
        <div>
          <label style={LABEL_STYLE}>Body</label>
          <textarea
            value={body}
            onChange={e => setBody(e.target.value)}
            rows={5}
            style={{ ...INPUT_STYLE, resize: 'vertical' }}
            maxLength={10000}
          />
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Btn variant="amber" onClick={handleSend} disabled={submitting}>
            {submitting ? 'Sending…' : 'Send'}
          </Btn>
          <Btn variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Btn>
        </div>
        {error && <p style={{ color: 'var(--danger)', fontSize: 13, margin: 0 }}>{error}</p>}
      </div>
    </Card>
  )
}

export default function Mail() {
  const [tab, setTab] = useState('inbox')
  const [messages, setMessages] = useState([])
  const [myNation, setMyNation] = useState(null)
  const [nations, setNations] = useState([])
  const [loading, setLoading] = useState(true)
  const [composing, setComposing] = useState(false)
  const [composeRecipient, setComposeRecipient] = useState(null)
  const [composeSubject, setComposeSubject] = useState('')
  const [expandedId, setExpandedId] = useState(null)
  const [expandedMsg, setExpandedMsg] = useState(null)
  const [loadingMsg, setLoadingMsg] = useState(false)
  const [error, setError] = useState('')

  const loadList = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch(`/api/mail/${tab}`, { credentials: 'include' })
      if (r.ok) setMessages(await r.json())
    } catch {
      setError('Failed to load')
    } finally {
      setLoading(false)
    }
  }, [tab])

  useEffect(() => { loadList() }, [loadList])

  useEffect(() => {
    fetch('/api/nations/mine', { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(n => { if (n) setMyNation(n) })
    fetch('/api/nations', { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(n => { if (n) setNations(n) })
  }, [])

  const handleRowClick = async (msg) => {
    if (expandedId === msg.id) {
      setExpandedId(null)
      setExpandedMsg(null)
      return
    }
    setExpandedId(msg.id)
    setLoadingMsg(true)
    try {
      const r = await fetch(`/api/mail/${msg.id}`, { credentials: 'include' })
      if (r.ok) {
        const detail = await r.json()
        setExpandedMsg(detail)
        setMessages(prev => prev.map(m => m.id === msg.id ? { ...m, read: true } : m))
      }
    } catch {}
    setLoadingMsg(false)
  }

  const handleDelete = async (msgId, e) => {
    e.stopPropagation()
    await fetch(`/api/mail/${msgId}`, { method: 'DELETE', credentials: 'include' })
    setMessages(prev => prev.filter(m => m.id !== msgId))
    if (expandedId === msgId) {
      setExpandedId(null)
      setExpandedMsg(null)
    }
  }

  const handleReply = (msg) => {
    setComposeRecipient(msg.sender_nation_id)
    setComposeSubject(`Re: ${msg.subject.replace(/^Re: /i, '')}`)
    setComposing(true)
  }

  const handleSent = () => {
    setComposing(false)
    setComposeRecipient(null)
    setComposeSubject('')
    if (tab === 'outbox') loadList()
  }

  const tabBtn = (key, label) => (
    <button
      key={key}
      onClick={() => {
        setTab(key)
        setExpandedId(null)
        setExpandedMsg(null)
      }}
      style={{
        padding: '7px 16px', fontSize: 13, cursor: 'pointer',
        background: tab === key ? 'var(--amber-dim)' : 'transparent',
        color: tab === key ? 'var(--amber)' : 'var(--text-secondary)',
        border: `1px solid ${tab === key ? 'var(--amber)' : 'var(--border)'}`,
        borderRadius: 'var(--radius-sm)',
      }}
    >
      {label}
    </button>
  )

  const unreadCount = messages.filter(m => !m.read).length

  return (
    <div>
      <div style={{
        display: 'flex', alignItems: 'flex-start',
        justifyContent: 'space-between', marginBottom: 28,
      }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600 }}>Mail</h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>
            Direct messages between nations
          </p>
        </div>
        <Btn
          variant="amber"
          onClick={() => {
            setComposeRecipient(null)
            setComposeSubject('')
            setComposing(c => !c)
          }}
        >
          {composing ? 'Cancel' : 'Compose'}
        </Btn>
      </div>

      {composing && (
        <ComposeForm
          nations={nations}
          myNation={myNation}
          prefillRecipientId={composeRecipient}
          prefillSubject={composeSubject}
          onSent={handleSent}
          onCancel={() => setComposing(false)}
        />
      )}

      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {tabBtn('inbox', `Inbox${unreadCount > 0 && tab === 'inbox' ? ` (${unreadCount} unread)` : ''}`)}
        {tabBtn('outbox', 'Outbox')}
      </div>

      {error && <p style={{ color: 'var(--danger)', marginBottom: 12 }}>{error}</p>}

      <Card style={{ padding: 0 }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
        ) : messages.length === 0 ? (
          <EmptyState
            title={tab === 'inbox' ? 'No mail' : 'No sent mail'}
            body={
              tab === 'inbox'
                ? 'Messages from other nations will appear here.'
                : 'Mail you send will appear here.'
            }
          />
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={TH_STYLE}>{tab === 'inbox' ? 'From' : 'To'}</th>
                <th style={TH_STYLE}>Subject</th>
                <th style={TH_STYLE}>Date</th>
                <th style={TH_STYLE}></th>
              </tr>
            </thead>
            <tbody>
              {messages.map(msg => (
                <React.Fragment key={msg.id}>
                  <tr
                    onClick={() => handleRowClick(msg)}
                    style={{
                      borderBottom: '1px solid var(--border)',
                      cursor: 'pointer',
                      background: expandedId === msg.id ? 'var(--bg-hover)' : '',
                    }}
                    onMouseEnter={e => {
                      if (expandedId !== msg.id) e.currentTarget.style.background = 'var(--bg-hover)'
                    }}
                    onMouseLeave={e => {
                      if (expandedId !== msg.id) e.currentTarget.style.background = ''
                    }}
                  >
                    <td style={{ padding: '10px 14px', fontSize: 13, color: 'var(--text-primary)' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        {tab === 'inbox' && !msg.read && (
                          <span style={{
                            width: 6, height: 6, borderRadius: '50%',
                            background: 'var(--amber)', flexShrink: 0,
                          }} />
                        )}
                        {tab === 'inbox' ? msg.sender_nation_name : msg.recipient_nation_name}
                      </span>
                    </td>
                    <td style={{
                      padding: '10px 14px', fontSize: 13,
                      color: tab === 'inbox' && !msg.read ? 'var(--text-primary)' : 'var(--text-secondary)',
                      fontWeight: tab === 'inbox' && !msg.read ? 600 : 400,
                    }}>
                      {msg.subject}
                    </td>
                    <td style={{
                      padding: '10px 14px', fontSize: 12,
                      color: 'var(--text-muted)', whiteSpace: 'nowrap',
                    }}>
                      {fmtDate(msg.sent_at)}
                    </td>
                    <td style={{ padding: '10px 14px' }}>
                      <button
                        onClick={(e) => handleDelete(msg.id, e)}
                        style={{
                          fontSize: 12, color: 'var(--text-muted)', background: 'none',
                          border: 'none', cursor: 'pointer', padding: '2px 6px',
                        }}
                        title="Delete"
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                  {expandedId === msg.id && (
                    <tr>
                      <td colSpan={4} style={{
                        padding: '16px 20px', background: 'var(--bg-elevated)',
                        borderBottom: '1px solid var(--border)',
                      }}>
                        {loadingMsg ? (
                          <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading…</span>
                        ) : expandedMsg ? (
                          <div>
                            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
                              {tab === 'inbox'
                                ? `From: ${expandedMsg.sender_nation_name}`
                                : `To: ${expandedMsg.recipient_nation_name}`}
                              {' · '}
                              {new Date(expandedMsg.sent_at).toLocaleString()}
                            </div>
                            <div style={{
                              fontSize: 13, color: 'var(--text-primary)',
                              lineHeight: 1.7, whiteSpace: 'pre-wrap', marginBottom: 16,
                            }}>
                              {expandedMsg.body}
                            </div>
                            {tab === 'inbox' && (
                              <Btn
                                variant="ghost"
                                style={{ fontSize: 12, padding: '4px 12px' }}
                                onClick={() => handleReply(expandedMsg)}
                              >
                                Reply
                              </Btn>
                            )}
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
