import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const HEX_SIZE = 9
const SVG_W = 700
const SVG_H = 560

function hexToSvg(q, r) {
  return [
    SVG_W / 2 + HEX_SIZE * (Math.sqrt(3) * q + (Math.sqrt(3) / 2) * r),
    SVG_H / 2 + HEX_SIZE * (1.5 * r),
  ]
}

function distanceColor(dist) {
  if (dist <= 2)  return '#f4a261'
  if (dist <= 6)  return '#457b9d'
  if (dist <= 10) return '#52796f'
  return '#6c757d'
}

// ── Step 1: Nation Identity ───────────────────────────────────────────────────

function StepIdentity({ data, onChange, onNext }) {
  const [error, setError] = useState('')

  const handleNext = () => {
    if (!data.name.trim() || data.name.trim().length < 3) {
      setError('Nation name must be at least 3 characters')
      return
    }
    if (!data.currency_name.trim()) {
      setError('Currency name is required')
      return
    }
    setError('')
    onNext()
  }

  return (
    <div>
      <h2>Name Your Nation</h2>
      <div>
        <label>Nation Name</label>
        <input
          type="text"
          value={data.name}
          onChange={e => onChange('name', e.target.value)}
          maxLength={128}
          placeholder="e.g. The Solari Compact"
          autoFocus
        />
      </div>
      <div>
        <label>Currency Name</label>
        <input
          type="text"
          value={data.currency_name}
          onChange={e => onChange('currency_name', e.target.value)}
          maxLength={64}
          placeholder="e.g. Credits"
        />
      </div>
      <div>
        <label>Nation Color</label>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <input
            type="color"
            value={data.flag_color}
            onChange={e => onChange('flag_color', e.target.value)}
            style={{ width: 48, height: 36, cursor: 'pointer', border: 'none', padding: 0 }}
          />
          <span style={{
            display: 'inline-block', width: 80, height: 36,
            background: data.flag_color, borderRadius: 4
          }} />
          <span style={{ color: '#888', fontSize: 13 }}>{data.flag_color.toUpperCase()}</span>
        </div>
      </div>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      <button onClick={handleNext}>Next: Choose Home System &rarr;</button>
    </div>
  )
}

// ── Step 2: Map Picker ────────────────────────────────────────────────────────

function StepMapPicker({ selectedId, onSelect, onNext, onBack, territories, loading, fetchError }) {
  const [hovered, setHovered] = useState(null)
  const [error, setError] = useState('')

  const handleNext = () => {
    if (!selectedId) { setError('Select a home system first'); return }
    setError('')
    onNext()
  }

  const tooltip = hovered
    ? territories.find(t => t.id === hovered)
    : selectedId
    ? territories.find(t => t.id === selectedId)
    : null

  return (
    <div>
      <h2>Choose Your Home System</h2>
      <p style={{ color: '#888', fontSize: 13 }}>
        Click a node to select your starting territory.
        Orange nodes are resource-rich core systems; blue and green are mid-range;
        grey nodes are quiet rim systems with lower conflict.
      </p>

      {loading && <p>Loading map&hellip;</p>}
      {fetchError && <p style={{ color: 'red' }}>{fetchError}</p>}

      {!loading && territories.length === 0 && (
        <p style={{ color: '#aaa' }}>
          No territories available. Run the territory seeder first:<br />
          <code>docker compose exec backend python -m app.seed</code>
        </p>
      )}

      {!loading && territories.length > 0 && (
        <svg
          width={SVG_W}
          height={SVG_H}
          style={{ background: '#0d1117', borderRadius: 8, display: 'block' }}
        >
          {territories.map(t => {
            const [q, r] = t.node_key.split(',').map(Number)
            const [x, y] = hexToSvg(q, r)
            const isSelected = t.id === selectedId
            const isHovered = t.id === hovered
            return (
              <circle
                key={t.id}
                cx={x}
                cy={y}
                r={isSelected ? 5.5 : 3.5}
                fill={distanceColor(t.distance_from_center)}
                stroke={isSelected ? '#fff' : isHovered ? '#ccc' : 'none'}
                strokeWidth={isSelected ? 1.5 : 1}
                style={{ cursor: 'pointer', opacity: isHovered || isSelected ? 1 : 0.7 }}
                onClick={() => onSelect(t.id)}
                onMouseEnter={() => setHovered(t.id)}
                onMouseLeave={() => setHovered(null)}
              />
            )
          })}
        </svg>
      )}

      {tooltip && (
        <p style={{ fontSize: 13, color: '#ccc', marginTop: 8 }}>
          System <strong>{tooltip.node_key}</strong> &mdash;
          Minerals: {tooltip.mineral_richness.toFixed(2)} &nbsp;
          Fuel: {tooltip.fuel_richness.toFixed(2)} &nbsp;
          Distance from core: {tooltip.distance_from_center}
        </p>
      )}

      {error && <p style={{ color: 'red' }}>{error}</p>}
      <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
        <button onClick={onBack}>&larr; Back</button>
        <button onClick={handleNext} disabled={!selectedId}>
          Next: Confirm &rarr;
        </button>
      </div>
    </div>
  )
}

// ── Step 3: Confirm ───────────────────────────────────────────────────────────

function StepConfirm({ data, territory, onSubmit, onBack, loading, error }) {
  return (
    <div>
      <h2>Ready to Launch</h2>
      <table>
        <tbody>
          <tr><td>Nation</td><td><strong>{data.name}</strong></td></tr>
          <tr><td>Currency</td><td>{data.currency_name}</td></tr>
          <tr>
            <td>Color</td>
            <td>
              <span style={{
                display: 'inline-block', width: 60, height: 22,
                background: data.flag_color, borderRadius: 3,
                verticalAlign: 'middle', marginRight: 8
              }} />
              {data.flag_color.toUpperCase()}
            </td>
          </tr>
          <tr>
            <td>Home System</td>
            <td>
              {territory
                ? `${territory.node_key} (minerals ${territory.mineral_richness.toFixed(2)}, fuel ${territory.fuel_richness.toFixed(2)})`
                : '—'}
            </td>
          </tr>
        </tbody>
      </table>
      {error && <p style={{ color: 'red', marginTop: 12 }}>{error}</p>}
      <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
        <button onClick={onBack} disabled={loading}>&larr; Back</button>
        <button onClick={onSubmit} disabled={loading}>
          {loading ? 'Launching…' : 'Launch Nation'}
        </button>
      </div>
    </div>
  )
}

// ── Wizard Shell ──────────────────────────────────────────────────────────────

export default function NationCreate() {
  const navigate = useNavigate()
  const { refreshPlayer } = useAuth()
  const [step, setStep] = useState(1)
  const [form, setForm] = useState({ name: '', currency_name: 'Credits', flag_color: '#3A86FF' })
  const [selectedTerritoryId, setSelectedTerritoryId] = useState(null)
  const [territories, setTerritories] = useState([])
  const [territoriesLoading, setTerritoriesLoading] = useState(false)
  const [territoriesError, setTerritoriesError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  useEffect(() => {
    if (step !== 2 || territories.length > 0) return
    setTerritoriesLoading(true)
    fetch('/api/territories/available', { credentials: 'include' })
      .then(r => r.json())
      .then(data => { setTerritories(data); setTerritoriesLoading(false) })
      .catch(() => { setTerritoriesError('Failed to load territories'); setTerritoriesLoading(false) })
  }, [step])

  const onChange = (field, value) => setForm(f => ({ ...f, [field]: value }))

  const handleSubmit = async () => {
    setSubmitting(true)
    setSubmitError('')
    try {
      const r = await fetch('/api/nations', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name.trim(),
          currency_name: form.currency_name.trim(),
          flag_color: form.flag_color.toUpperCase(),
          home_territory_id: selectedTerritoryId,
        }),
      })
      if (!r.ok) {
        const err = await r.json()
        setSubmitError(err.detail || 'Failed to create nation')
        return
      }
      await refreshPlayer()
      navigate('/', { replace: true })
    } catch {
      setSubmitError('Network error — please try again')
    } finally {
      setSubmitting(false)
    }
  }

  const selectedTerritory = territories.find(t => t.id === selectedTerritoryId) ?? null

  return (
    <div style={{ maxWidth: 760, margin: '40px auto', padding: '0 20px' }}>
      <h1>Found Your Nation</h1>
      <p style={{ color: '#888' }}>Step {step} of 3</p>

      {step === 1 && (
        <StepIdentity
          data={form}
          onChange={onChange}
          onNext={() => setStep(2)}
        />
      )}
      {step === 2 && (
        <StepMapPicker
          selectedId={selectedTerritoryId}
          onSelect={setSelectedTerritoryId}
          onNext={() => setStep(3)}
          onBack={() => setStep(1)}
          territories={territories}
          loading={territoriesLoading}
          fetchError={territoriesError}
        />
      )}
      {step === 3 && (
        <StepConfirm
          data={form}
          territory={selectedTerritory}
          onSubmit={handleSubmit}
          onBack={() => setStep(2)}
          loading={submitting}
          error={submitError}
        />
      )}
    </div>
  )
}
