/** What a screen says while it is reading, when it failed, and when there is nothing to show. */
export function ScreenState({
  phase,
  empty,
  failed = 'Could not read this from the server. The call path is unaffected.',
}: {
  phase: 'loading' | 'ready' | 'failed'
  empty?: string | null
  failed?: string
}) {
  if (phase === 'loading') return <p className="screen__waiting">Reading…</p>
  if (phase === 'failed')
    return (
      <p className="screen__waiting" role="alert">
        {failed}
      </p>
    )
  return empty ? <p className="screen__empty">{empty}</p> : null
}
