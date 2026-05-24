import { useState, useEffect } from 'react'
import { useNation } from '../hooks/useNation'
import { PageHeader, Card } from '../components/ui'

const HEX_SIZE = 9
const SVG_W = 800
const SVG_H = 640

function hexToSvg(q, r) {
  return [
    SVG_W / 2 + HEX_SIZE * (Math.sqrt(3) * q + (Math.sqrt(3) / 2) * r),
    SVG_H / 2 + HEX_SIZE * 1.5 * r,
  ]
}

function territoryColor(t, myNationId, isHome) {
  if (isHome) return '#3ec9b4'
  if (t.nation_id === myNationId) return '#3ec9b4'
  if (t.nation_id) return '#9268d4'
  if (t.distance_from_center <= 2)  return '#e8943a'
  if (t.distance_from_center <= 6)  return '#457b9d'
  if (t.distance_from_center <= 10) return '#52796f'
  return '#2a2f50'
}

export default function MapView() {
  const { nation } = useNation()
  const [territories, setTerritories] = useState([])
  const [loading, setLoading] = useState(true)
  const [hovered, setHovered] = useState(null)

  useEffect(() => {
    fetch('/api/territories', { credentials: 'include' })
      .then(r => r.ok ? r.json() : [])
      .then(data => { setTerritories(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const tooltip = hovered ? territories.find(t => t.id === hovered) : null

  return (
    <div>
      <PageHeader
        title="Map"
        sub="The shared galaxy — orange: core, blue: mid-range, grey: rim"
      />

      {/* Legend */}
      <div style={{ display: 'flex', gap: 20, marginBottom: 16, fontSize: 12, color: 'var(--text-secondary)' }}>
        {[
          { color: '#3ec9b4', label: 'Your territory' },
          { color: '#9268d4', label: 'Other nations' },
          { color: '#e8943a', label: 'Unclaimed core' },
          { color: '#457b9d', label: 'Unclaimed mid' },
          { color: '#52796f', label: 'Unclaimed mid-rim' },
          { color: '#2a2f50', label: 'Rim' },
        ].map(({ color, label }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block' }} />
            {label}
          </div>
        ))}
      </div>

      <Card style={{ padding: 12 }}>
        {loading ? (
          <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 40 }}>Loading map&hellip;</p>
        ) : territories.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 40 }}>
            No territory data. Run the seeder: <code>docker compose exec backend python -m app.seed</code>
          </p>
        ) : (
          <svg
            width={SVG_W}
            height={SVG_H}
            style={{ background: '#07080f', borderRadius: 6, display: 'block', margin: '0 auto' }}
          >
            {territories.map(t => {
              const [q, r] = t.node_key.split(',').map(Number)
              const [x, y] = hexToSvg(q, r)
              const isHome = nation?.home_territory_id === t.id
              const isMine = t.nation_id === nation?.id
              const isHovered = t.id === hovered
              const fill = territoryColor(t, nation?.id, isHome)
              const r2 = isHome ? 6 : isMine ? 5 : isHovered ? 4.5 : 3.5

              return (
                <circle
                  key={t.id}
                  cx={x} cy={y} r={r2}
                  fill={fill}
                  stroke={isHome ? '#fff' : isHovered ? '#aaa' : 'none'}
                  strokeWidth={isHome ? 1.5 : 1}
                  opacity={isHovered || isMine ? 1 : 0.75}
                  style={{ cursor: 'pointer' }}
                  onMouseEnter={() => setHovered(t.id)}
                  onMouseLeave={() => setHovered(null)}
                />
              )
            })}
          </svg>
        )}
      </Card>

      {/* Tooltip */}
      <div style={{ height: 28, marginTop: 10, fontSize: 13, color: 'var(--text-secondary)' }}>
        {tooltip && (
          <>
            <strong style={{ color: 'var(--text-primary)' }}>{tooltip.node_key}</strong>
            {' — '}
            {tooltip.nation_name
              ? <span style={{ color: 'var(--purple)' }}>{tooltip.nation_name}</span>
              : <span style={{ color: 'var(--text-muted)' }}>Unclaimed</span>
            }
            {' · '}
            Distance {tooltip.distance_from_center}
            {tooltip.mineral_richness != null && (
              <> &nbsp; Min {Number(tooltip.mineral_richness).toFixed(2)} &nbsp; Fuel {Number(tooltip.fuel_richness).toFixed(2)}</>
            )}
          </>
        )}
      </div>
    </div>
  )
}
