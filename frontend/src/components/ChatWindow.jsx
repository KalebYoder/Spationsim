import { useState, useEffect, useRef, useCallback } from 'react'

const dmChannel = (a, b) => `dm_${Math.min(a, b)}_${Math.max(a, b)}`

const MSG_STYLE = { fontSize: 12, padding: '2px 0', lineHeight: 1.5, wordBreak: 'break-word' }
const INPUT_STYLE = {
  flex: 1, background: 'var(--bg-base)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', padding: '6px 10px',
  fontSize: 13, outline: 'none',
}

export default function ChatWindow() {
  const [expanded, setExpanded] = useState(false)
  const [activeTab, setActiveTab] = useState('general')
  const [openDmTabs, setOpenDmTabs] = useState([])
  const [messages, setMessages] = useState({})
  const [unread, setUnread] = useState({})
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [showDmPicker, setShowDmPicker] = useState(false)
  const [nations, setNations] = useState([])
  const [myNation, setMyNation] = useState(null)

  const activeTabRef = useRef(activeTab)
  const messagesRef = useRef({})
  const lastIdRef = useRef({})
  const loadedRef = useRef(new Set())
  const openDmTabsRef = useRef([])
  const msgListRef = useRef(null)

  useEffect(() => { activeTabRef.current = activeTab }, [activeTab])
  useEffect(() => { openDmTabsRef.current = openDmTabs }, [openDmTabs])

  useEffect(() => {
    fetch('/api/nations/mine', { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(n => { if (n) setMyNation(n) })
  }, [])

  const scrollToBottom = useCallback(() => {
    if (msgListRef.current) {
      msgListRef.current.scrollTop = msgListRef.current.scrollHeight
    }
  }, [])

  const loadChannel = useCallback(async (channel) => {
    if (loadedRef.current.has(channel)) return
    loadedRef.current.add(channel)
    try {
      const r = await fetch(`/api/chat/messages?channel=${encodeURIComponent(channel)}`, { credentials: 'include' })
      if (!r.ok) return
      const data = await r.json()
      messagesRef.current = { ...messagesRef.current, [channel]: data }
      setMessages({ ...messagesRef.current })
      lastIdRef.current[channel] = data.length > 0 ? data[data.length - 1].id : 0
    } catch {}
    setTimeout(scrollToBottom, 50)
  }, [scrollToBottom])

  useEffect(() => {
    if (expanded && myNation) {
      loadChannel(activeTab)
      setUnread(prev => ({ ...prev, [activeTab]: 0 }))
    }
  }, [expanded, activeTab, myNation, loadChannel])

  useEffect(() => {
    if (!expanded || !myNation) return
    const poll = async () => {
      const channels = ['general', 'trade', ...openDmTabsRef.current.map(t => t.channel)]
      for (const ch of channels) {
        if (!loadedRef.current.has(ch)) continue
        const afterId = lastIdRef.current[ch] ?? 0
        try {
          const r = await fetch(
            `/api/chat/messages?channel=${encodeURIComponent(ch)}&after_id=${afterId}`,
            { credentials: 'include' }
          )
          if (!r.ok) continue
          const newMsgs = await r.json()
          if (newMsgs.length === 0) continue
          const existing = messagesRef.current[ch] ?? []
          messagesRef.current = { ...messagesRef.current, [ch]: [...existing, ...newMsgs] }
          setMessages({ ...messagesRef.current })
          lastIdRef.current[ch] = newMsgs[newMsgs.length - 1].id
          if (ch === activeTabRef.current) {
            setTimeout(scrollToBottom, 50)
          } else {
            setUnread(prev => ({ ...prev, [ch]: (prev[ch] ?? 0) + newMsgs.length }))
          }
        } catch {}
      }
    }
    const id = setInterval(poll, 4000)
    return () => clearInterval(id)
  }, [expanded, myNation, openDmTabs, scrollToBottom])

  const handleSend = async () => {
    const content = input.trim()
    if (!content || sending) return
    setSending(true)
    try {
      const r = await fetch('/api/chat/messages', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel: activeTab, content }),
      })
      if (r.ok) {
        const msg = await r.json()
        messagesRef.current = {
          ...messagesRef.current,
          [activeTab]: [...(messagesRef.current[activeTab] ?? []), msg],
        }
        setMessages({ ...messagesRef.current })
        lastIdRef.current[activeTab] = msg.id
        setInput('')
        setTimeout(scrollToBottom, 50)
      }
    } catch {}
    setSending(false)
  }

  const openDm = useCallback((otherId, otherName) => {
    const ch = dmChannel(myNation.id, otherId)
    if (!openDmTabsRef.current.find(t => t.channel === ch)) {
      setOpenDmTabs(prev => [...prev, { channel: ch, otherNationId: otherId, otherNationName: otherName }])
    }
    setActiveTab(ch)
    setShowDmPicker(false)
  }, [myNation])

  const closeDmTab = (channel, e) => {
    e.stopPropagation()
    setOpenDmTabs(prev => prev.filter(t => t.channel !== channel))
    if (activeTab === channel) setActiveTab('general')
  }

  const fetchNations = async () => {
    if (nations.length > 0) return
    const r = await fetch('/api/nations', { credentials: 'include' })
    if (r.ok) setNations(await r.json())
  }

  const allTabs = [
    { key: 'general', label: 'General' },
    { key: 'trade', label: 'Trade' },
    ...openDmTabs.map(t => ({ key: t.channel, label: t.otherNationName, isDm: true })),
  ]

  const totalUnread = Object.entries(unread)
    .filter(([k]) => k !== activeTab)
    .reduce((s, [, v]) => s + v, 0)

  const tabStyle = (key) => ({
    padding: '0 10px',
    height: 32,
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    fontSize: 12,
    cursor: 'pointer',
    color: key === activeTab ? 'var(--amber)' : 'var(--text-secondary)',
    whiteSpace: 'nowrap',
    background: 'none',
    border: 'none',
    borderBottom: `2px solid ${key === activeTab ? 'var(--amber)' : 'transparent'}`,
    flexShrink: 0,
  })

  const currentMessages = messages[activeTab] ?? []

  return (
    <div style={{
      position: 'fixed', bottom: 0, right: 20, width: 320, zIndex: 1000,
      display: 'flex', flexDirection: 'column',
      boxShadow: '0 -2px 20px rgba(0,0,0,0.4)',
    }}>
      {/* Header */}
      <div
        onClick={() => setExpanded(e => !e)}
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-mid)',
          borderBottom: expanded ? '1px solid var(--border)' : '1px solid var(--border-mid)',
          padding: '0 14px',
          height: 40,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          borderRadius: expanded ? 0 : '6px 6px 0 0',
          userSelect: 'none',
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>
          Chat
          {totalUnread > 0 && (
            <span style={{
              marginLeft: 8, background: 'var(--amber)', color: '#000',
              borderRadius: 10, padding: '1px 6px', fontSize: 11, fontWeight: 700,
            }}>
              {totalUnread}
            </span>
          )}
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{expanded ? '▼' : '▲'}</span>
      </div>

      {expanded && (
        <div style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-mid)',
          borderTop: 'none',
          display: 'flex',
          flexDirection: 'column',
        }}>
          {/* Tab bar */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            borderBottom: '1px solid var(--border)',
            overflowX: 'auto',
            height: 34,
          }}>
            {allTabs.map(tab => (
              <div
                key={tab.key}
                onClick={() => {
                  setActiveTab(tab.key)
                  setUnread(prev => ({ ...prev, [tab.key]: 0 }))
                }}
                style={tabStyle(tab.key)}
              >
                {tab.label}
                {unread[tab.key] > 0 && (
                  <span style={{
                    background: 'var(--amber)', color: '#000',
                    borderRadius: 10, padding: '0 5px', fontSize: 10, fontWeight: 700,
                  }}>
                    {unread[tab.key]}
                  </span>
                )}
                {tab.isDm && (
                  <span
                    onClick={(e) => closeDmTab(tab.key, e)}
                    style={{
                      marginLeft: 4, color: 'var(--text-muted)',
                      fontSize: 11, cursor: 'pointer', lineHeight: 1,
                    }}
                  >
                    ×
                  </span>
                )}
              </div>
            ))}

            {/* +DM button */}
            <div style={{ marginLeft: 'auto', position: 'relative', flexShrink: 0 }}>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  fetchNations()
                  setShowDmPicker(p => !p)
                }}
                style={{
                  padding: '0 10px', height: 32, fontSize: 12,
                  color: 'var(--text-muted)', background: 'none',
                  border: 'none', cursor: 'pointer',
                }}
              >
                + DM
              </button>
              {showDmPicker && (
                <div style={{
                  position: 'absolute', bottom: '100%', right: 0, width: 180,
                  background: 'var(--bg-elevated)', border: '1px solid var(--border-mid)',
                  borderRadius: 'var(--radius-sm)', maxHeight: 200, overflowY: 'auto', zIndex: 10,
                }}>
                  {nations.filter(n => n.id !== myNation?.id).length === 0 && (
                    <div style={{ padding: '10px 12px', fontSize: 12, color: 'var(--text-muted)' }}>
                      No other nations
                    </div>
                  )}
                  {nations.filter(n => n.id !== myNation?.id).map(n => (
                    <div
                      key={n.id}
                      onClick={() => openDm(n.id, n.name)}
                      style={{
                        padding: '8px 12px', fontSize: 13, cursor: 'pointer',
                        display: 'flex', alignItems: 'center', gap: 8,
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                      onMouseLeave={e => e.currentTarget.style.background = ''}
                    >
                      <span style={{
                        width: 8, height: 8, borderRadius: '50%',
                        background: n.flag_color, flexShrink: 0,
                      }} />
                      {n.name}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Message list */}
          <div
            ref={msgListRef}
            style={{
              height: 260, overflowY: 'auto', padding: '8px 12px',
              display: 'flex', flexDirection: 'column', gap: 2,
            }}
          >
            {currentMessages.length === 0 && (
              <div style={{
                color: 'var(--text-muted)', fontSize: 12,
                textAlign: 'center', marginTop: 40,
              }}>
                No messages yet
              </div>
            )}
            {currentMessages.map(msg => {
              const isOwn = msg.sender_nation_id === myNation?.id
              return (
                <div key={msg.id} style={MSG_STYLE}>
                  <span style={{
                    fontWeight: 600,
                    color: isOwn ? 'var(--teal)' : 'var(--amber)',
                    marginRight: 6,
                    fontSize: 11,
                  }}>
                    {msg.sender_nation_name}
                  </span>
                  <span style={{ color: 'var(--text-primary)' }}>{msg.content}</span>
                </div>
              )
            })}
          </div>

          {/* Input */}
          <div style={{
            display: 'flex', gap: 6, padding: '8px 10px',
            borderTop: '1px solid var(--border)',
          }}>
            <input
              style={INPUT_STYLE}
              placeholder={`Message #${activeTab.startsWith('dm_') ? 'dm' : activeTab}…`}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              maxLength={500}
            />
            <button
              onClick={handleSend}
              disabled={sending || !input.trim()}
              style={{
                padding: '6px 12px', fontSize: 12,
                background: 'var(--amber-dim)', color: 'var(--amber)',
                border: '1px solid var(--amber)', borderRadius: 'var(--radius-sm)',
                cursor: sending || !input.trim() ? 'not-allowed' : 'pointer',
                opacity: sending || !input.trim() ? 0.5 : 1,
              }}
            >
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
