import type { ApiErrorDetail, FieldError } from './types'

// ── Error class ──────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: ApiErrorDetail,
  ) {
    super(typeof detail === 'string' ? detail : 'Request validation failed')
    this.name = 'ApiError'
  }

  /** True when the detail is a list of field-level errors. */
  isFieldError(): this is ApiError & { detail: FieldError[] } {
    return Array.isArray(this.detail)
  }

  /** Returns a flat string for simple display (joins field errors if needed). */
  getDetail(): string {
    if (typeof this.detail === 'string') return this.detail
    return this.detail.map((e) => `${e.field}: ${e.message}`).join('; ')
  }
}

// ── Token store ──────────────────────────────────────────────────────────────

const TOKEN_KEY = 'bb_access_token'

export const tokenStore = {
  get: (): string | null => localStorage.getItem(TOKEN_KEY),
  set: (token: string): void => localStorage.setItem(TOKEN_KEY, token),
  clear: (): void => localStorage.removeItem(TOKEN_KEY),
}

// ── Base client ──────────────────────────────────────────────────────────────

const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  const token = tokenStore.get()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${BASE}/api/v1${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!res.ok) {
    let detail: ApiErrorDetail = `HTTP ${res.status}`
    try {
      const json = await res.json()
      if (json?.detail !== undefined) detail = json.detail
    } catch {
      // non-JSON error body — keep the default message
    }
    throw new ApiError(res.status, detail)
  }

  // 204 No Content
  if (res.status === 204) return undefined as T

  return res.json() as Promise<T>
}

export const api = {
  get:    <T>(path: string)                  => request<T>('GET',    path),
  post:   <T>(path: string, body?: unknown)  => request<T>('POST',   path, body),
  patch:  <T>(path: string, body?: unknown)  => request<T>('PATCH',  path, body),
  delete: <T>(path: string)                  => request<T>('DELETE', path),
}
