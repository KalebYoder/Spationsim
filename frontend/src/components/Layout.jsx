import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useNation } from '../hooks/useNation'

const NAV = [
  { to: '/',          label: 'Nation',     end: true },
  { to: '/economy',   label: 'Economy'               },
  { to: '/facilities',label: 'Facilities'            },
  { to: '/military',  label: 'Military'              },
  { to: '/probes',    label: 'Probes'                },
  { to: '/planets',   label: 'Planets'               },
  { to: '/map',       label: 'Map'                   },
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
          {NAV.map(({ to, label, end }) => (
            <NavLink key={to} to={to} end={end} style={navLinkStyle}>
              {label}
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
    </div>
  )
}
