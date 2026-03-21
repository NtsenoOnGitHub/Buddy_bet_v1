import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { authApi } from '../api/auth'
import { useAuth } from '../auth/AuthContext'
import { Input } from '../components/ui/Input'
import { Button } from '../components/ui/Button'
import { ErrorMessage } from '../components/ui/ErrorMessage'
import { getErrorMessage } from '../utils/errors'

const schema = z.object({
  email:        z.string().email('Enter a valid email'),
  display_name: z.string().min(2, 'At least 2 characters').max(100),
  password:     z.string().min(8, 'At least 8 characters').max(128),
})

type FormData = z.infer<typeof schema>

export default function RegisterPage() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [globalError, setGlobalError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema) })

  async function onSubmit(data: FormData) {
    setGlobalError(null)
    try {
      const res = await authApi.register(data)
      login(res.access_token, res.user)
      navigate('/dashboard')
    } catch (err) {
      setGlobalError(getErrorMessage(err))
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-950 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold text-white">
            Buddy<span className="text-brand-400">Bet</span>
          </h1>
          <p className="mt-2 text-sm text-gray-400">Create your account</p>
        </div>

        <form
          onSubmit={handleSubmit(onSubmit)}
          className="space-y-4 rounded-xl border border-gray-800 bg-gray-900 p-6"
        >
          {globalError && <ErrorMessage error={globalError} />}

          <Input
            label="Email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            error={errors.email?.message}
            {...register('email')}
          />
          <Input
            label="Display name"
            type="text"
            autoComplete="nickname"
            placeholder="Thabo M"
            error={errors.display_name?.message}
            {...register('display_name')}
          />
          <Input
            label="Password"
            type="password"
            autoComplete="new-password"
            placeholder="Min 8 characters"
            error={errors.password?.message}
            {...register('password')}
          />

          <Button type="submit" className="w-full" loading={isSubmitting}>
            Create account
          </Button>

          <p className="text-center text-sm text-gray-500">
            Already have an account?{' '}
            <Link to="/login" className="text-brand-400 hover:underline">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
