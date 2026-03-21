import { ApiError } from '../api/client'
import type { FieldError } from '../api/types'
import { UseFormSetError, FieldValues, Path } from 'react-hook-form'

/**
 * Extract a human-readable error string from anything that might be thrown.
 * Safe to call with unknown values from catch blocks.
 */
export function getErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.getDetail()
  if (err instanceof Error) return err.message
  return 'An unexpected error occurred.'
}

/**
 * Pipe API field errors into a react-hook-form `setError` call.
 * Returns true if any field errors were set, false if it was a simple error.
 */
export function applyFieldErrors<T extends FieldValues>(
  err: unknown,
  setError: UseFormSetError<T>,
  setGlobal?: (msg: string) => void,
): boolean {
  if (!(err instanceof ApiError)) {
    setGlobal?.(getErrorMessage(err))
    return false
  }
  if (err.isFieldError()) {
    err.detail.forEach((fe: FieldError) => {
      setError(fe.field as Path<T>, { message: fe.message })
    })
    return true
  }
  setGlobal?.(err.getDetail())
  return false
}
