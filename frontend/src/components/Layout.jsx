import { useState, useEffect } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useNation } from '../hooks/useNation'
import ChatWindow from './ChatWindow'

const NAV = [
  { to: '/',           label: 'Nation',     end: true         },
  { to: '/economy',    label: 'Economy'                       },
  { to: '/facilities', label: 'Facilities'                    },
  { to: '/military',   label: 'Military'                      },
  { to: '/probes',     label: 'Probes'                        },
  { to: '/planets',    label: 'Planets'                       },
  { to: '/map',        label: 'Map'                           },
  { to: '/diplomacy',  label: 'Diplomacy'                     },
  { to: '/friends',    label: 'Friends',    friendBadge: true },
  { to: '/mail',       label: 'Mail',       badge: true       },
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
  const [mailUnread, setMailUnread] = useState(0)
  const [friendPending, setFriendPending] = useState(0)

  useEffect(() => {
    const fetchUnread = () => {
      fetch('/api/mail/unread-count', { credentials: 'include' })
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data) setMailUnread(data.count) })
        .catch(() => {})
    }
    fetchUnread()
    const id = setInterval(fetchUnread, 30000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (!nation) return
    const fetchFriendPending = () => {
      fetch('/api/diplomacy/friends', { credentials: 'include' })
        .then(r => r.ok ? r.json() : [])
        .then(data => {
          const incoming = data.filter(e => e.status === 'friend_pending' && e.requested_by !== nation.id).length
          setFriendPending(incoming)
        })
        .catch(() => {})
    }
    fetchFriendPending()
    const id = setInterval(fetchFriendPending, 60000)
    return () => clearInterval(id)
  }, [nation])

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
          {NAV.map(({ to, label, end, badge, friendBadge }) => (
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
              </span>
            </NavLink>
          ))}
        </div>

        {/* Footer */}
        <div style={{
          padding: '12px 18px',
          borderTop: '1px solid var(--border)',
          fontSize: 12,
          color: 'var(--text-muted)',
        }}>
          <div style={{ marginBottom: 6, color: 'var(--text-secondary)' }}>
            {player?.username}
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
        padding: '28px 32px',
        background: 'var(--bg-base)',
      }}>
        <Outlet />
      </main>

      <ChatWindow />
    </div>
  )
}
