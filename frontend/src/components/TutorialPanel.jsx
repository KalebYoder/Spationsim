const STEPS = [
  { step: 1, title: "Build a Mine", desc: "Construct a mine on your home planet to begin extracting minerals.", reward: "+500 minerals, +500 currency on completion" },
  { step: 2, title: "Build a Refinery", desc: "Construct a refinery to produce fuel for ships and probes.", reward: "+500 fuel, +500 currency on completion" },
  { step: 3, title: "Review Planet Production", desc: "Visit the Planets tab to see your resource gain and loss rates.", reward: "+100 minerals, +100 fuel, +500 currency on completion" },
  { step: 4, title: "Build a Shipyard", desc: "The shipyard is required for all military and exploration units.", reward: "+1000 currency on completion" },
]

export default function TutorialPanel({ tutorial, dismiss }) {
  if (!tutorial || tutorial.current_step > 4 || tutorial.dismissed) return null

  const current = STEPS.find(s => s.step === tutorial.current_step)
  if (!current) return null

  return (
    <div style={{
      margin: '12px 8px 4px',
      padding: '12px 14px',
      background: 'var(--bg-base)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius-sm)',
    }}>
      <div style={{
        fontSize: 10,
        textTransform: 'uppercase',
        letterSpacing: '0.1em',
        color: 'var(--text-muted)',
        marginBottom: 8,
        fontWeight: 600,
      }}>
        Tutorial
      </div>

      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--amber)' }}>
          {current.title}
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Step {tutorial.current_step} of 4
        </span>
      </div>

      <p style={{ fontSize: 12, color: 'var(--text-secondary)', margin: '0 0 6px', lineHeight: 1.5 }}>
        {current.desc}
      </p>

      {current.reward && (
        <p style={{ fontSize: 11, color: 'var(--teal)', margin: '0 0 8px' }}>
          {current.reward}
        </p>
      )}

      <button
        onClick={dismiss}
        style={{
          background: 'none',
          border: 'none',
          padding: 0,
          cursor: 'pointer',
          color: 'var(--text-muted)',
          fontSize: 11,
        }}
      >
        Skip tutorial
      </button>
    </div>
  )
}
