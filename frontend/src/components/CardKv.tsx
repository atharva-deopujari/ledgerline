import { keyAsWords } from './format'

/**
 * A card's key/value fields, printed under its head. The plan card usually carries none —
 * its figures live in its rows — but anything the engine does put here is shown rather than
 * dropped, under the backend's own field name read as words.
 */
export function CardKv({ kv }: { kv: Record<string, string> }) {
  const entries = Object.entries(kv)
  if (entries.length === 0) return null
  return (
    <dl className="kv">
      {entries.map(([key, value]) => (
        <div className="kv__pair" key={key}>
          <dt>{keyAsWords(key)}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}
