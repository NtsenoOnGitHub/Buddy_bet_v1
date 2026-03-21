import type { ApiErrorDetail } from '../../api/types'

interface ErrorMessageProps {
  error: ApiErrorDetail | string | null | undefined
}

export function ErrorMessage({ error }: ErrorMessageProps) {
  if (!error) return null

  if (typeof error === 'string') {
    return (
      <div className="rounded-lg border border-red-700/50 bg-red-900/20 px-4 py-3 text-sm text-red-300">
        {error}
      </div>
    )
  }

  // FieldError[]
  return (
    <div className="rounded-lg border border-red-700/50 bg-red-900/20 px-4 py-3 text-sm text-red-300">
      <ul className="space-y-1">
        {error.map((fe) => (
          <li key={fe.field}>
            <span className="font-medium">{fe.field}:</span> {fe.message}
          </li>
        ))}
      </ul>
    </div>
  )
}
