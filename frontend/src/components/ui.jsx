/* Shared UI primitives */

export function PageHeader({ title, sub }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <h1 style={{ fontSize: 22, fontWeight: 600, color: 'var(--text-primary)' }}>{title}</h1>
      {sub && <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: 13 }}>{sub}</p>}
    </div>
  )
}

export function Card({ children, style }) {
  return (
    <div style={{
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
      padding: '20px 24px',
      ...style,
    }}>
      {children}
    </div>
  )
}

export function StatCard({ label, value, sub, accent, subColor }) {
  return (
    <Card>
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 600, color: accent || 'var(--text-primary)', lineHeight: 1 }}>
        {value ?? '—'}
      </div>
      {sub && <div style={{ fontSize: 12, color: subColor || 'var(--text-muted)', marginTop: 6 }}>{sub}</div>}
    </Card>
  )
}

export function SectionLabel({ children }) {
  return (
    <div style={{
      fontSize: 11,
      textTransform: 'uppercase',
      letterSpacing: '0.1em',
      color: 'var(--text-muted)',
      marginBottom: 12,
      marginTop: 28,
    }}>
      {children}
    </div>
  )
}

export function AlertBanner({ type = 'warning', children }) {
  const colors = {
    warning: { bg: 'var(--amber-dim)', border: 'var(--amber)', text: 'var(--amber)' },
    danger:  { bg: 'var(--danger-dim)', border: 'var(--danger)', text: 'var(--danger)' },
    info:    { bg: 'var(--teal-dim)', border: 'var(--teal)', text: 'var(--teal)' },
  }
  const c = colors[type]
  return (
    <div style={{
      background: c.bg,
      border: `1px solid ${c.border}`,
      borderRadius: 'var(--radius-sm)',
      padding: '10px 16px',
      color: c.text,
      fontSize: 13,
      marginBottom: 8,
    }}>
      {children}
    </div>
  )
}

export function EmptyState({ title, body }) {
  return (
    <div style={{
      textAlign: 'center',
      padding: '60px 32px',
      color: 'var(--text-muted)',
    }}>
      <div style={{ fontSize: 15, marginBottom: 8, color: 'var(--text-secondary)' }}>{title}</div>
      {body && <div style={{ fontSize: 13 }}>{body}</div>}
    </div>
  )
}

export function Table({ headers, children, style }) {
  return (
    <div style={{ overflowX: 'auto', ...style }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            {headers.map(h => (
              <th key={h} style={{
                textAlign: 'left',
                padding: '8px 14px',
                fontSize: 11,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'var(--text-muted)',
                borderBottom: '1px solid var(--border)',
              }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

export function Tr({ children, onClick }) {
  return (
    <tr
      onClick={onClick}
      style={{ borderBottom: '1px solid var(--border)', cursor: onClick ? 'pointer' : 'default' }}
      onMouseEnter={e => { if (onClick) e.currentTarget.style.background = 'var(--bg-hover)' }}
      onMouseLeave={e => { e.currentTarget.style.background = '' }}
    >
      {children}
    </tr>
  )
}

export function Td({ children, muted, accent, style }) {
  return (
    <td style={{
      padding: '10px 14px',
      color: accent ? `var(--${accent})` : muted ? 'var(--text-secondary)' : 'var(--text-primary)',
      fontSize: 13,
      ...style,
    }}>
      {children}
    </td>
  )
}

export function Badge({ children, color = 'teal' }) {
  const colors = {
    teal:   { bg: 'var(--teal-dim)',   text: 'var(--teal)'   },
    amber:  { bg: 'var(--amber-dim)',  text: 'var(--amber)'  },
    purple: { bg: 'var(--purple-dim)', text: 'var(--purple)' },
    rose:   { bg: 'var(--rose-dim)',   text: 'var(--rose)'   },
    danger: { bg: 'var(--danger-dim)', text: 'var(--danger)' },
    muted:  { bg: 'var(--bg-hover)',   text: 'var(--text-secondary)' },
  }
  const c = colors[color] || colors.muted
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 10,
      fontSize: 11,
      fontWeight: 600,
      background: c.bg,
      color: c.text,
      letterSpacing: '0.04em',
    }}>
      {children}
    </span>
  )
}

export function Btn({ children, onClick, variant = 'primary', disabled, style }) {
  const variants = {
    primary: { bg: 'var(--teal-dim)', color: 'var(--teal)', border: '1px solid var(--teal)' },
    amber:   { bg: 'var(--amber-dim)', color: 'var(--amber)', border: '1px solid var(--amber)' },
    danger:  { bg: 'var(--danger-dim)', color: 'var(--danger)', border: '1px solid var(--danger)' },
    ghost:   { bg: 'transparent', color: 'var(--text-secondary)', border: '1px solid var(--border)' },
  }
  const v = variants[variant] || variants.primary
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: '7px 16px',
        borderRadius: 'var(--radius-sm)',
        background: v.bg,
        color: v.color,
        border: v.border,
        fontWeight: 500,
        opacity: disabled ? 0.5 : 1,
        ...style,
      }}
    >
      {children}
    </button>
  )
}
