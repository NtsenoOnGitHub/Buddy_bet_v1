import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
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
import { Card } from '../components/ui/Card'
import { PageSpinner } from '../components/ui/Spinner'
import { formatDate, formatRelative } from '../utils/date'
import { getErrorMessage } from '../utils/errors'

const PREDICTIONS: { value: FootballOutcome; label: string }[] = [
  { value: 'home_win', label: 'Home Win' },
  { value: 'away_win', label: 'Away Win' },
  { value: 'draw',     label: 'Draw' },
]

const schema = z.object({
  match_id: z.string().min(1, 'Select a match'),
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
  const [searchParams] = useSearchParams()
  const prefilledMatchId = searchParams.get('matchId')

  const [globalError, setGlobalError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    control,
    setValue,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema) })

  // ── Mode A: prefilled from match list ──────────────────────────────────
  // Fetch the specific match when a matchId is provided via query param.
  const {
    data: prefilledMatch,
    isLoading: prefilledLoading,
    error: prefilledError,
  } = useQuery({
    queryKey: ['match', prefilledMatchId],
    queryFn: () => matchesApi.get(prefilledMatchId!),
    enabled: !!prefilledMatchId,
  })

  // Wire prefilled match id into the form once loaded.
  useEffect(() => {
    if (prefilledMatch?.id) {
      setValue('match_id', prefilledMatch.id, { shouldValidate: false })
    }
  }, [prefilledMatch, setValue])

  // ── Mode B: dropdown (no matchId param) ────────────────────────────────
  // Fetch scheduled matches for the selector.
  const { data: matchListData, isLoading: matchesLoading } = useQuery({
    queryKey: ['matches', 'scheduled'],
    queryFn: () => matchesApi.list({ page: 1, pageSize: 50, status: 'scheduled' }),
    enabled: !prefilledMatchId,
  })

  // For the kickoff hint shown below the dropdown
  const selectedMatchId = watch('match_id')
  const dropdownSelectedMatch = matchListData?.items.find((m) => m.id === selectedMatchId)

  // ── Submit ─────────────────────────────────────────────────────────────
  async function onSubmit(data: FormData) {
    setGlobalError(null)
    try {
      const bet = await betsApi.create(data)
      navigate(`/bets/${bet.id}`)
    } catch (err) {
      setGlobalError(getErrorMessage(err))
    }
  }

  // ── Loading state (prefilled mode only) ────────────────────────────────
  if (prefilledMatchId && prefilledLoading) return <PageSpinner />

  // ── Prefilled match fetch failed ───────────────────────────────────────
  if (prefilledMatchId && prefilledError) {
    return (
      <div className="mx-auto max-w-lg">
        <ErrorMessage error={getErrorMessage(prefilledError)} />
        <div className="mt-3">
          <Button variant="secondary" onClick={() => navigate('/matches')}>
            Back to Matches
          </Button>
        </div>
      </div>
    )
  }

  // ── Betting closed for this match ──────────────────────────────────────
  if (prefilledMatchId && prefilledMatch && !prefilledMatch.is_betting_open) {
    return (
      <div className="mx-auto max-w-lg">
        <Card>
          <p className="text-center font-medium text-gray-300">
            Betting is no longer open for this match.
          </p>
          <p className="mt-1 text-center text-sm text-gray-500">
            {prefilledMatch.home_team} vs {prefilledMatch.away_team}
          </p>
          <div className="mt-4 flex justify-center">
            <Button variant="secondary" onClick={() => navigate('/matches')}>
              Back to Matches
            </Button>
          </div>
        </Card>
      </div>
    )
  }

  // ── Main form ─────────────────────────────────────────────────────────
  return (
    <div className="mx-auto max-w-lg">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Create a Bet</h1>
        <p className="mt-1 text-sm text-gray-400">
          Make your prediction and set your stake.
        </p>
      </div>

      <Card>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
          {globalError && <ErrorMessage error={globalError} />}

          {/* ── Match: prefilled display ─────────────────────────── */}
          {prefilledMatch ? (
            <div>
              <p className="mb-1 text-sm font-medium text-gray-300">Match</p>
              <div className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2.5">
                <p className="text-sm font-semibold text-white">
                  {prefilledMatch.home_team}{' '}
                  <span className="font-normal text-gray-500">vs</span>{' '}
                  {prefilledMatch.away_team}
                </p>
                <p className="mt-0.5 text-xs text-gray-500">
                  {prefilledMatch.competition} · kicks off{' '}
                  {formatRelative(prefilledMatch.kickoff_at)} ·{' '}
                  {formatDate(prefilledMatch.kickoff_at)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => navigate('/matches')}
                className="mt-1 text-xs text-gray-500 underline hover:text-gray-300"
              >
                Choose a different match
              </button>
              {/* Keeps match_id registered and valued in the form */}
              <input type="hidden" {...register('match_id')} />
            </div>
          ) : (
            /* ── Match: dropdown (no matchId param) ──────────────── */
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
                {matchListData?.items
                  .filter((m) => m.is_betting_open)
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.home_team} vs {m.away_team} — {m.competition}
                    </option>
                  ))}
              </select>
              {errors.match_id && (
                <p className="text-xs text-red-400">{errors.match_id.message}</p>
              )}
              {dropdownSelectedMatch && (
                <p className="text-xs text-gray-500">
                  Kick-off: {formatDate(dropdownSelectedMatch.kickoff_at)}
                </p>
              )}
            </div>
          )}

          {/* ── Prediction ──────────────────────────────────────────── */}
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
                      disabled={isSubmitting}
                      onClick={() => field.onChange(value)}
                      className={[
                        'rounded-lg border py-2 text-sm font-medium transition-colors',
                        'disabled:cursor-not-allowed disabled:opacity-50',
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

          {/* ── Stake ───────────────────────────────────────────────── */}
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
              onClick={() => {
                if (prefilledMatchId) navigate('/matches')
                else navigate(-1)
              }}
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
