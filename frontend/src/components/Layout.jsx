import { useState, useEffect, useRef } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useNation } from '../hooks/useNation'
import { useTutorial } from '../hooks/useTutorial'
import ChatWindow from './ChatWindow'
import TutorialPanel from './TutorialPanel'
import NationSearch from './NationSearch'

const NAV = [
  { to: '/',           label: 'Nation',     end: true         },
  { to: '/economy',    label: 'Economy'                       },
  { to: '/facilities', label: 'Facilities'                    },
  { to: '/military',   label: 'Military',   threatBadge: true  },
  { to: '/probes',     label: 'Probes'                        },
  { to: '/market',     label: 'Market'                        },
  { to: '/planets',    label: 'Planets'                       },
  { to: '/map',        label: 'Map'                           },
  { to: '/diplomacy',  label: 'Diplomacy'                     },
  { to: '/friends',    label: 'Friends',    friendBadge: true  },
  { to: '/trade',      label: 'Trade',      tradeBadge: true   },
  { to: '/mail',       label: 'Mail',       badge: true        },
  { to: '/log',        label: 'Event Log'                     },
]

const navLinkStyle = ({ isActive }) => ({
  display: 'block',
  padding: '8px 16px',
  borderRadius: 'var(--radius-sm)',
  borderLeft: `2px solid ${isActive ? 'var(--amber)' : 'transparent'}`,
  color: isActive ? 'var(--amber)' : 'var(--text-secondary)',
  background: isActive ? 'var(--amber-dim)' : 'transparent',
  marginBottom: 2,
  transition: 'color 0.15s, background 0.15s',
  letterSpacing: '0.03em',
})

export default function Layout() {
  const { player, logout } = useAuth()
  const { nation } = useNation()
  const { tutorial, dismiss, completeStep9 } = useTutorial()
  const [mailUnread, setMailUnread] = useState(0)
  const [friendPending, setFriendPending] = useState(0)
  const [tradeIncoming, setTradeIncoming] = useState(0)
  const [threatCount, setThreatCount] = useState(0)
  const [notifPerm, setNotifPerm] = useState(
    typeof Notification !== 'undefined' ? Notification.permission : 'unsupported'
  )
  const prevCounts = useRef(null)

  const fireNotification = (title, body) => {
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return
    new Notification(title, { body, icon: '/favicon.ico' })
  }

  const requestNotifPermission = () => {
    if (typeof Notification === 'undefined') return
    Notification.requestPermission().then(perm => setNotifPerm(perm))
  }

  useEffect(() => {
    const fetchNotifications = () => {
      fetch('/api/notifications', { credentials: 'include' })
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (!data) return
          const threat = data.threat_count ?? 0
          const pending = data.fleet_pending_action ?? 0
          const prev = prevCounts.current
          if (prev) {
            if (threat > prev.threat)
              fireNotification('Spationsim — Threat detected', 'An enemy fleet has arrived at your territory.')
            if (pending > prev.pending)
              fireNotification('Spationsim — Fleet awaiting orders', 'Your fleet has arrived and is waiting for your command.')
          }
          prevCounts.current = { threat, pending }
          setMailUnread(data.mail_unread)
          setFriendPending(data.friend_pending)
          setTradeIncoming(data.trade_incoming)
          setThreatCount(threat)
        })
        .catch(() => {})
    }
    fetchNotifications()
    const id = setInterval(fetchNotifications, 45000)
    return () => clearInterval(id)
  }, [])

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* Sidebar */}
      <nav style={{
        width: 'var(--nav-width)',
        flexShrink: 0,
        background: 'var(--bg-surface)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        padding: '0',
        overflowY: 'auto',
      }}>
        {/* Logo */}
        <div style={{
          padding: '20px 18px 16px',
          borderBottom: '1px solid var(--border)',
          marginBottom: 8,
        }}>
          <div style={{
            fontSize: 13,
            fontWeight: 700,
            letterSpacing: '0.15em',
            color: 'var(--teal)',
            textTransform: 'uppercase',
          }}>
            Spationsim
          </div>
          {nation && (
            <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                display: 'inline-block',
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: nation.flag_color,
                flexShrink: 0,
              }} />
              <span style={{
                color: 'var(--text-primary)',
                fontSize: 13,
                fontWeight: 500,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}>
                {nation.name}
              </span>
            </div>
          )}
        </div>

        {/* Nav links */}
        <div style={{ flex: 1, padding: '0 8px' }}>
          {NAV.map(({ to, label, end, badge, friendBadge, tradeBadge, threatBadge }) => (
            <NavLink key={to} to={to} end={end} style={navLinkStyle}>
              <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                {label}
                {badge && mailUnread > 0 && (
                  <span style={{
                    background: 'var(--amber)',
                    color: '#000',
                    borderRadius: 10,
                    padding: '1px 6px',
                    fontSize: 10,
                    fontWeight: 700,
                    lineHeight: 1.4,
                  }}>
                    {mailUnread}
                  </span>
                )}
                {friendBadge && friendPending > 0 && (
                  <span style={{
                    background: '#5a8a62',
                    color: '#fff',
                    borderRadius: 10,
                    padding: '1px 6px',
                    fontSize: 10,
                    fontWeight: 700,
                    lineHeight: 1.4,
                  }}>
                    {friendPending}
                  </span>
                )}
                {tradeBadge && tradeIncoming > 0 && (
                  <span style={{
                    background: 'var(--amber)',
                    color: '#000',
                    borderRadius: 10,
                    padding: '1px 6px',
                    fontSize: 10,
                    fontWeight: 700,
                    lineHeight: 1.4,
                  }}>
                    {tradeIncoming}
                  </span>
                )}
                {threatBadge && threatCount > 0 && (
                  <span style={{
                    background: 'var(--danger)',
                    color: '#fff',
                    borderRadius: 10,
                    padding: '1px 6px',
                    fontSize: 10,
                    fontWeight: 700,
                    lineHeight: 1.4,
                  }}>
                    {threatCount}
                  </span>
                )}
              </span>
            </NavLink>
          ))}
        </div>

        {tutorial && !tutorial.dismissed && tutorial.current_step <= 10 && (
          <TutorialPanel tutorial={tutorial} dismiss={dismiss} completeStep9={completeStep9} />
        )}

        {/* Footer */}
        <div style={{
          padding: '12px 18px',
          borderTop: '1px solid var(--border)',
          fontSize: 12,
          color: 'var(--text-muted)',
        }}>
          <div style={{ marginBottom: 6, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ color: 'var(--text-secondary)' }}>{player?.username}</span>
            {notifPerm !== 'unsupported' && (
              <button
                onClick={notifPerm === 'default' ? requestNotifPermission : undefined}
                title={
                  notifPerm === 'granted' ? 'Browser alerts enabled' :
                  notifPerm === 'denied'  ? 'Alerts blocked — allow in browser settings' :
                  'Enable browser alerts'
                }
                style={{
                  background: 'none',
                  padding: '2px 4px',
                  fontSize: 14,
                  lineHeight: 1,
                  color: notifPerm === 'granted' ? 'var(--teal)' : 'var(--text-muted)',
                  cursor: notifPerm === 'default' ? 'pointer' : 'default',
                  opacity: notifPerm === 'denied' ? 0.4 : 1,
                }}
              >
                {notifPerm === 'granted' ? '🔔' : '🔕'}
              </button>
            )}
          </div>
          <button
            onClick={logout}
            style={{
              background: 'none',
              color: 'var(--text-muted)',
              padding: 0,
              fontSize: 12,
            }}
          >
            Log out
          </button>
        </div>
      </nav>

      {/* Main content */}
      <main style={{
        flex: 1,
        overflow: 'auto',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--bg-base)',
      }}>
        {/* Top bar with nation search */}
        <div style={{
          display: 'flex',
          justifyContent: 'flex-end',
          alignItems: 'center',
          padding: '10px 32px',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}>
          <NationSearch />
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: '28px 32px' }}>
          <Outlet />
        </div>
      </main>

      <ChatWindow />
    </div>
  )
}
