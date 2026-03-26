import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { authApi } from '../api/auth'
import { Input } from '../components/ui/Input'
import { Button } from '../components/ui/Button'
import { ErrorMessage } from '../components/ui/ErrorMessage'
import { getErrorMessage } from '../utils/errors'

const schema = z
  .object({
    new_password: z
      .string()
      .min(8, 'Password must be at least 8 characters'),
    confirm_password: z.string().min(1, 'Confirm your new password'),
  })
  .refine((d) => d.new_password === d.confirm_password, {
    message: 'Passwords do not match',
    path: ['confirm_password'],
  })

type FormData = z.infer<typeof schema>

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [success, setSuccess] = useState(false)
  const [globalError, setGlobalError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema) })

  async function onSubmit(data: FormData) {
    setGlobalError(null)
    try {
      await authApi.resetPassword({ token, new_password: data.new_password })
      setSuccess(true)
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
          <p className="mt-2 text-sm text-gray-400">Choose a new password</p>
        </div>

        <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
          {/* Missing token */}
          {!token ? (
            <div className="space-y-3 text-center">
              <p className="text-sm text-gray-400">
                This reset link is missing a token. Please request a new one.
              </p>
              <Link
                to="/forgot-password"
                className="text-sm text-brand-400 hover:underline"
              >
                Request password reset
              </Link>
            </div>
          ) : success ? (
            /* ── Success ──────────────────────────────────────────── */
            <div className="space-y-4 text-center">
              <p className="font-medium text-green-400">
                Password updated successfully.
              </p>
              <p className="text-sm text-gray-400">
                You can now sign in with your new password.
              </p>
              <Link
                to="/login"
                className="block text-sm text-brand-400 hover:underline"
              >
                Go to sign in →
              </Link>
            </div>
          ) : (
            /* ── Reset form ───────────────────────────────────────── */
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              {globalError && <ErrorMessage error={globalError} />}

              <Input
                label="New password"
                type="password"
                autoComplete="new-password"
                placeholder="••••••••"
                hint="At least 8 characters."
                error={errors.new_password?.message}
                {...register('new_password')}
              />

              <Input
                label="Confirm new password"
                type="password"
                autoComplete="new-password"
                placeholder="••••••••"
                error={errors.confirm_password?.message}
                {...register('confirm_password')}
              />

              <Button type="submit" className="w-full" loading={isSubmitting}>
                Set new password
              </Button>

              <p className="text-center text-sm text-gray-500">
                Remembered it?{' '}
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
