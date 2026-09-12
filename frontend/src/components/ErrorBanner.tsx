interface Props {
  message: string | null
  onRetry: () => void
  /** A retry is pointless while a call is already coming up. */
  disabled?: boolean
}

export function ErrorBanner({ message, onRetry, disabled = false }: Props) {
  if (!message) return null
  return (
    <div className="error" role="alert">
      <p className="error__text">{message}</p>
      <button type="button" className="error__retry" onClick={onRetry} disabled={disabled}>
        Try again
      </button>
    </div>
  )
}
