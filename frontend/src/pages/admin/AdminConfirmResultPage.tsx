import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { matchesApi } from '../../api/matches'
import { adminApi } from '../../api/admin'
import type { FootballOutcome, SettlementSummaryResponse } from '../../api/types'
import { Card, CardHeader, CardTitle } from '../../components/ui/Card'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Input'
import { ErrorMessage } from '../../components/ui/ErrorMessage'
import { PageSpinner } from '../../components/ui/Spinner'
import { formatDate } from '../../utils/date'
import { getErrorMessage } from '../../utils/errors'

const OUTCOMES: { value: FootballOutcome; label: string }[] = [
  { value: 'home_win', label: 'Home Win' },
  { value: 'away_win', label: 'Away Win' },
  { value: 'draw',     label: 'Draw' },
]

const schema = z.object({
  match_id: z.string().min(1, 'Select a match'),
  outcome: z.enum(['home_win', 'away_win', 'draw'], { required_error: 'Select an outcome' }),
  home_score: z
    .string()
    .min(1, 'Required')
    .refine((v) => !isNaN(parseInt(v, 10)) && parseInt(v, 10) >= 0, {
      message: 'Must be 0 or more',
    }),
  away_score: z
    .string()
    .min(1, 'Required')
    .refine((v) => !isNaN(parseInt(v, 10)) && parseInt(v, 10) >= 0, {
      message: 'Must be 0 or more',
    }),
})

type FormData = z.infer<typeof schema>

export default function AdminConfirmResultPage() {
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [lastResult, setLastResult]   = useState<SettlementSummaryResponse | null>(null)

  const { data: matchData, isLoading: matchesLoading } = useQuery({
    queryKey: ['matches', 'all'],
    queryFn: () => matchesApi.list(1, 100),
  })

  const {
    register,
    handleSubmit,
    control,
    watch,
    reset,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(schema) })

  const selectedMatchId = watch('match_id')
  const selectedMatch   = matchData?.items.find((m) => m.id === selectedMatchId)

  const confirmMutation = useMutation({
    mutationFn: (data: FormData) =>
      adminApi.confirmResult(data.match_id, {
        outcome:    data.outcome,
        home_score: parseInt(data.home_score, 10),
        away_score: parseInt(data.away_score, 10),
      }),
    onSuccess: (result) => {
      setSubmitError(null)
      setLastResult(result)
      reset()
    },
    onError: (err) => {
      setLastResult(null)
      setSubmitError(getErrorMessage(err))
    },
  })

  const actionableMatches = matchData?.items.filter(
    (m) => m.status === 'live' || m.status === 'completed',
  ) ?? []

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Confirm Match Result</h1>
        <p className="mt-1 text-sm text-gray-400">
          Set the final result of a match to trigger automatic settlement of all associated bets.
        </p>
      </div>

      {/* Settlement summary shown after successful confirmation */}
      {lastResult && (
        <Card>
          <CardHeader>
            <CardTitle>Settlement Summary</CardTitle>
          </CardHeader>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <div>
              <dt className="text-gray-500">Outcome confirmed</dt>
              <dd className="font-medium capitalize text-gray-200">
                {lastResult.outcome.replace(/_/g, ' ')}
              </dd>
            </div>
            <div>
              <dt className="text-gray-500">Bets found</dt>
              <dd className="font-medium text-gray-200">{lastResult.bets_found}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Settled</dt>
              <dd className="font-medium text-green-400">{lastResult.bets_settled}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Failed</dt>
              <dd className={`font-medium ${lastResult.bets_failed > 0 ? 'text-red-400' : 'text-gray-400'}`}>
                {lastResult.bets_failed}
              </dd>
            </div>
          </dl>
          {lastResult.bets_failed > 0 && (
            <div className="mt-3 space-y-1 rounded-lg border border-red-700/50 bg-red-900/20 p-3 text-xs text-red-300">
              <p className="font-semibold">Failed bets — use Pending Settlement to retry:</p>
              {lastResult.failed_bet_ids.map((id) => (
                <p key={id} className="font-mono">
                  {id}
                  {lastResult.failure_reasons[id] && (
                    <span className="ml-2 opacity-75">— {lastResult.failure_reasons[id]}</span>
                  )}
                </p>
              ))}
            </div>
          )}
        </Card>
      )}

      <Card>
        <form
          onSubmit={handleSubmit((data) => confirmMutation.mutate(data))}
          className="space-y-5"
        >
          {submitError && <ErrorMessage error={submitError} />}

          {/* Match selector */}
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium text-gray-300">Match</label>
            {matchesLoading ? (
              <p className="py-2 text-sm text-gray-500">Loading matches…</p>
            ) : actionableMatches.length === 0 ? (
              <p className="py-2 text-sm text-gray-500">No live or completed matches found.</p>
            ) : (
              <select
                className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                {...register('match_id')}
                defaultValue=""
              >
                <option value="" disabled>Select a match</option>
                {actionableMatches.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.home_team} vs {m.away_team} — {m.competition}
                    {m.outcome ? ' (already confirmed)' : ''}
                  </option>
                ))}
              </select>
            )}
            {errors.match_id && (
              <p className="text-xs text-red-400">{errors.match_id.message}</p>
            )}
            {selectedMatch && (
              <p className="text-xs text-gray-500">
                Kick-off: {formatDate(selectedMatch.kickoff_at)}
                {selectedMatch.outcome && (
                  <span className="ml-2 text-yellow-400">
                    Previously confirmed: {selectedMatch.outcome.replace(/_/g, ' ')}
                  </span>
                )}
              </p>
            )}
          </div>

          {/* Outcome selector */}
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-gray-300">Match Outcome</span>
            <Controller
              name="outcome"
              control={control}
              render={({ field }) => (
                <div className="grid grid-cols-3 gap-2">
                  {OUTCOMES.map(({ value, label }) => (
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
            {errors.outcome && (
              <p className="text-xs text-red-400">{errors.outcome.message}</p>
            )}
          </div>

          {/* Scores */}
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="Home Score"
              type="number"
              min="0"
              placeholder="0"
              error={errors.home_score?.message}
              {...register('home_score')}
            />
            <Input
              label="Away Score"
              type="number"
              min="0"
              placeholder="0"
              error={errors.away_score?.message}
              {...register('away_score')}
            />
          </div>

          <Button
            type="submit"
            className="w-full"
            loading={confirmMutation.isPending}
          >
            Confirm Result &amp; Settle Bets
          </Button>
        </form>
      </Card>
    </div>
  )
}
