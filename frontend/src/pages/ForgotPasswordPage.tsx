import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { authApi } from '../api/auth'
import { Input } from '../components/ui/Input'
import { Button } from '../components/ui/Button'
import { ErrorMessage } from '../components/ui/ErrorMessage'
import { getErrorMessage } from '../utils/errors'

const schema = z.object({
  email: z.string().email('Enter a valid email address'),
})

type FormData = z.infer<typeof schema>

export default function ForgotPasswordPage() {
  const [submitted, setSubmitted] = useState(false)
  const [devToken, setDevToken] = useState<string | null>(null)
  const [globalError, setGlobalError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema) })

  async function onSubmit(data: FormData) {
    setGlobalError(null)
    try {
      const res = await authApi.forgotPassword(data)
      setSubmitted(true)
      // In development the backend returns the token directly so we can test
      // the flow without an email service.
      if (res.reset_token) setDevToken(res.reset_token)
    } catch (err) {
      setGlobalError(getErrorMessage(err))
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-950 px-4">
      <div className="w-full max-w-sm">
        {/* Brand */}
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold text-white">
            Buddy<span className="text-brand-400">Bet</span>
          </h1>
          <p className="mt-2 text-sm text-gray-400">Reset your password</p>
        </div>

        <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
          {submitted ? (
            /* ── Success state ─────────────────────────────────────── */
            <div className="space-y-4">
              <p className="text-sm text-gray-300">
                If that email address is registered, a reset link has been sent.
                Check your inbox and follow the instructions.
              </p>

              {/* Dev-mode token display — never shown in production */}
              {devToken && (
                <div className="rounded-lg border border-yellow-700/50 bg-yellow-900/20 p-3">
                  <p className="mb-1 text-xs font-semibold text-yellow-400">
                    Development mode — reset token:
                  </p>
                  <p className="break-all font-mono text-xs text-yellow-300">
                    {devToken}
                  </p>
                  <Link
                    to={`/reset-password?token=${encodeURIComponent(devToken)}`}
                    className="mt-2 inline-block text-xs text-brand-400 underline hover:text-brand-300"
                  >
                    Go to reset form →
                  </Link>
                </div>
              )}

              <Link
                to="/login"
                className="block text-center text-sm text-brand-400 hover:underline"
              >
                Back to sign in
              </Link>
            </div>
          ) : (
            /* ── Request form ──────────────────────────────────────── */
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              {globalError && <ErrorMessage error={globalError} />}

              <p className="text-sm text-gray-400">
                Enter your email address and we'll send you a link to reset
                your password.
              </p>

              <Input
                label="Email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                error={errors.email?.message}
                {...register('email')}
              />

              <Button type="submit" className="w-full" loading={isSubmitting}>
                Send reset link
              </Button>

              <p className="text-center text-sm text-gray-500">
                Remember your password?{' '}
                <Link to="/login" className="text-brand-400 hover:underline">
                  Sign in
                </Link>
              </p>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
