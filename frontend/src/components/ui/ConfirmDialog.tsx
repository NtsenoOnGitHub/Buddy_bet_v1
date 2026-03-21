import { useEffect } from 'react'
import { Button } from './Button'

interface ConfirmDialogProps {
  open: boolean
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  destructive?: boolean
  loading?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/**
 * Modal confirmation dialog. Traps focus and closes on Escape.
 * Renders nothing when open=false so it is safe to always mount.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onCancel}
        aria-hidden
      />
      {/* Panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        className="relative z-10 w-full max-w-sm rounded-xl border border-gray-700 bg-gray-900 p-6 shadow-2xl"
      >
        <h2 id="confirm-dialog-title" className="text-base font-semibold text-white">
          {title}
        </h2>
        {description && (
          <p className="mt-2 text-sm text-gray-400">{description}</p>
        )}
        <div className="mt-5 flex justify-end gap-3">
          <Button variant="ghost" size="sm" disabled={loading} onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button
            variant={destructive ? 'danger' : 'primary'}
            size="sm"
            loading={loading}
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
