import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { depositsApi } from '../api/deposits'
import { Input } from '../components/ui/Input'
import { Button } from '../components/ui/Button'
import { ErrorMessage } from '../components/ui/ErrorMessage'
import { Card } from '../components/ui/Card'
import { getErrorMessage } from '../utils/errors'

const schema = z.object({
  amount: z
    .string()
    .min(1, 'Enter an amount')
    .refine((v) => !isNaN(parseFloat(v)) && parseFloat(v) > 0, {
      message: 'Amount must be a positive number',
    }),
})

type FormData = z.infer<typeof schema>

export default function DepositPage() {
  const navigate = useNavigate()
  const [globalError, setGlobalError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema) })

  async function onSubmit(data: FormData) {
    setGlobalError(null)
    try {
      const result = await depositsApi.initiate({ amount: data.amount })
      // Redirect browser to PayFast hosted checkout.
      // Wallet is credited ONLY after PayFast sends the ITN webhook —
      // never from this redirect alone.
      window.location.href = result.checkout_url
    } catch (err) {
      setGlobalError(getErrorMessage(err))
    }
  }

  return (
    <div className="mx-auto max-w-lg">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Deposit Funds</h1>
        <p className="mt-1 text-sm text-gray-400">
          Add ZAR to your Buddy Bet wallet via PayFast.
        </p>
      </div>

      <Card>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
          {globalError && <ErrorMessage error={globalError} />}

          <Input
            label="Amount (ZAR)"
            type="number"
            step="0.01"
            min="10"
            placeholder="100.00"
            hint="Minimum R10.00. You will be redirected to PayFast to complete payment."
            error={errors.amount?.message}
            {...register('amount')}
          />

          {/* Security note */}
          <div className="rounded-lg border border-gray-700 bg-gray-800/50 px-4 py-3">
            <p className="text-xs text-gray-400">
              Your wallet balance will update once PayFast confirms your
              payment — usually within a few seconds. If you return to the app
              before it updates, the status page will show the latest state.
            </p>
          </div>

          <div className="flex gap-3">
            <Button
              type="button"
              variant="secondary"
              className="flex-1"
              onClick={() => navigate('/wallet')}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button type="submit" className="flex-1" loading={isSubmitting}>
              Continue to PayFast
            </Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
