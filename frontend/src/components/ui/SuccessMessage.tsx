interface SuccessMessageProps {
  message: string
}

export function SuccessMessage({ message }: SuccessMessageProps) {
  if (!message) return null
  return (
    <div className="rounded-lg border border-green-700/50 bg-green-900/20 px-4 py-3 text-sm text-green-300">
      {message}
    </div>
  )
}
