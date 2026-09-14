import { useState } from 'react'

const ASK = 'Forget everything remembered about this number? This cannot be undone.'
const DONE = 'Forgotten. Nothing is kept about this number.'
const FAILED = 'Could not forget this number. Try again.'

type Stage = 'idle' | 'asking' | 'sending' | 'done' | 'failed'

/**
 * `DELETE /api/users/{phone}`: the profile facts and notes go, the calls stay with the phone
 * nulled. Irreversible, so it asks in the page first — never through a browser dialog, which
 * is both uglier and a thing an automated session cannot dismiss.
 */
export function ForgetButton({ phone, onForgotten }: { phone: string; onForgotten?: () => void }) {
  const [stage, setStage] = useState<Stage>('idle')
  if (!phone) return null
  if (stage === 'done') return <p className="forget__done">{DONE}</p>

  const forget = async () => {
    setStage('sending')
    try {
      const response = await fetch(`/api/users/${encodeURIComponent(phone)}`, { method: 'DELETE' })
      if (!response.ok) throw new Error(String(response.status))
    } catch {
      setStage('failed')
      return
    }
    setStage('done')
    onForgotten?.()
  }

  return (
    <div className="forget">
      {stage === 'asking' || stage === 'sending' ? (
        <>
          <p className="forget__ask">{ASK}</p>
          <button
            type="button"
            className="forget__confirm"
            onClick={() => void forget()}
            disabled={stage === 'sending'}
          >
            Yes, forget
          </button>
          <button
            type="button"
            className="forget__cancel"
            onClick={() => setStage('idle')}
            disabled={stage === 'sending'}
          >
            Cancel
          </button>
        </>
      ) : (
        <button type="button" className="forget__start" onClick={() => setStage('asking')}>
          Forget this number
        </button>
      )}
      {stage === 'failed' && (
        <p className="forget__failed" role="alert">
          {FAILED}
        </p>
      )}
    </div>
  )
}
