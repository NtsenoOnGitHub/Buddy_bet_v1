import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useQuery } from '@tanstack/react-query'
import { matchesApi } from '../api/matches'
import { betsApi } from '../api/bets'
import type { FootballOutcome } from '../api/types'
import { Input } from '../components/ui/Input'
import { Button } from '../components/ui/Button'
import { ErrorMessage } from '../components/ui/ErrorMessage'
import { Card, CardHeader, CardTitle } from '../components/ui/Card'
import { formatDate } from '../utils/date'
import { getErrorMessage } from '../utils/errors'

const PREDICTIONS: { value: FootballOutcome; label: string }[] = [
  { value: 'home_win', label: 'Home Win' },
  { value: 'away_win', label: 'Away Win' },
  { value: 'draw',     label: 'Draw' },
]

const schema = z.object({
  match_id:           z.string().min(1, 'Select a match'),
  creator_prediction: z.enum(['home_win', 'away_win', 'draw'], {
    required_error: 'Select a prediction',
  }),
  stake_amount: z
    .string()
    .min(1, 'Enter a stake amount')
    .refine((v) => !isNaN(parseFloat(v)) && parseFloat(v) > 0, {
      message: 'Stake must be a positive number',
    }),
})

type FormData = z.infer<typeof schema>

export default function CreateBetPage() {
  const navigate = useNavigate()
  const [globalError, setGlobalError] = useState<string | null>(null)

  const { data: matchData, isLoading: matchesLoading } = useQuery({
    queryKey: ['matches'],
    queryFn: () => matchesApi.list(1, 50),
  })

  const {
    register,
    handleSubmit,
    control,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema) })

  const selectedMatchId = watch('match_id')
  const selectedMatch = matchData?.items.find((m) => m.id === selectedMatchId)

  async function onSubmit(data: FormData) {
    setGlobalError(null)
    try {
      const bet = await betsApi.create(data)
      navigate(`/bets/${bet.id}`)
    } catch (err) {
      setGlobalError(getErrorMessage(err))
    }
  }

  return (
    <div className="mx-auto max-w-lg">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Place a Bet</h1>
        <p className="mt-1 text-sm text-gray-400">
          Choose a match, make your prediction, and set your stake.
        </p>
      </div>

      <Card>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
          {globalError && <ErrorMessage error={globalError} />}

          {/* Match selector */}
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium text-gray-300">Match</label>
            <select
              className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              {...register('match_id')}
              defaultValue=""
            >
              <option value="" disabled>
                {matchesLoading ? 'Loading matches…' : 'Select a match'}
              </option>
              {matchData?.items.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.home_team} vs {m.away_team} — {m.competition}
                </option>
              ))}
            </select>
            {errors.match_id && (
              <p className="text-xs text-red-400">{errors.match_id.message}</p>
            )}
            {selectedMatch && (
              <p className="text-xs text-gray-500">
                Kick-off: {formatDate(selectedMatch.kickoff_at)}
              </p>
            )}
          </div>

          {/* Prediction */}
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-gray-300">Your Prediction</span>
            <Controller
              name="creator_prediction"
              control={control}
              render={({ field }) => (
                <div className="grid grid-cols-3 gap-2">
                  {PREDICTIONS.map(({ value, label }) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => field.onChange(value)}
                      className={[
                        'rounded-lg border py-2 text-sm font-medium transition-colors',
                        field.value === value
                          ? 'border-brand-500 bg-brand-500/20 text-brand-300'
                          : 'border-gray-700 bg-gray-800 text-gray-300 hover:border-gray-500',
                      ].join(' ')}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
            />
            {errors.creator_prediction && (
              <p className="text-xs text-red-400">{errors.creator_prediction.message}</p>
            )}
          </div>

          {/* Stake */}
          <Input
            label="Stake amount (ZAR)"
            type="number"
            step="0.01"
            min="0.01"
            placeholder="100.00"
            hint="Enter a positive amount. Your stake will be locked immediately."
            error={errors.stake_amount?.message}
            {...register('stake_amount')}
          />

          <div className="flex gap-3 pt-1">
            <Button
              type="button"
              variant="secondary"
              className="flex-1"
              onClick={() => navigate(-1)}
            >
              Cancel
            </Button>
            <Button type="submit" className="flex-1" loading={isSubmitting}>
              Place Bet
            </Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
