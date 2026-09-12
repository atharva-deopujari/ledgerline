/** Summary-style cards carry a small key/value grid instead of rows. */
export function CardKv({ kv }: { kv: Record<string, string> }) {
  const entries = Object.entries(kv)
  if (entries.length === 0) return null
  return (
    <dl className="kv">
      {entries.map(([key, value]) => (
        <div className="kv__pair" key={key}>
          {/* Keys arrive as backend field names: `unpaid_total` reads as two words. */}
          <dt>{key.replace(/_/g, ' ')}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}
