import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm, Controller } from 'react-hook-form'
import { betsApi } from '../api/bets'
import type { FootballOutcome, SettlementOutcome } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Card, CardHeader, CardTitle } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { BetStatusBadge } from '../components/bet/BetStatusBadge'
import { ErrorMessage } from '../components/ui/ErrorMessage'
import { SuccessMessage } from '../components/ui/SuccessMessage'
import { PageSpinner } from '../components/ui/Spinner'
import { formatMoney } from '../utils/money'
import { formatDate } from '../utils/date'
import { getErrorMessage } from '../utils/errors'

const OUTCOME_LABELS: Record<FootballOutcome, string> = {
  home_win: 'Home Win',
  away_win: 'Away Win',
  draw:     'Draw',
}

const SETTLEMENT_LABELS: Record<SettlementOutcome, string> = {
  creator_wins:  'Creator Won',
  opponent_wins: 'Opponent Won',
  no_winner:     'No Winner',
  voided:        'Voided',
}

const ALL_PREDICTIONS: FootballOutcome[] = ['home_win', 'away_win', 'draw']

export default function BetDetailPage() {
  const { betId }  = useParams<{ betId: string }>()
  const navigate   = useNavigate()
  const { user }   = useAuth()
  const queryClient = useQueryClient()

  const [actionError,   setActionError]   = useState<string | null>(null)
  const [actionSuccess, setActionSuccess] = useState<string | null>(null)

  const { data: bet, isLoading, error } = useQuery({
    queryKey: ['bet', betId],
    queryFn: () => betsApi.get(betId!),
    enabled: !!betId,
  })

  const { control, handleSubmit, watch, formState: { errors: formErrors } } =
    useForm<{ opponent_prediction: FootballOutcome }>()
  const chosenPrediction = watch('opponent_prediction')

  const acceptMutation = useMutation({
    mutationFn: (pred: FootballOutcome) =>
      betsApi.accept(betId!, { opponent_prediction: pred }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['bet', betId], updated)
      queryClient.invalidateQueries({ queryKey: ['bets'] })
      setActionError(null)
      setActionSuccess('Bet accepted! Your stake has been locked.')
    },
    onError: (err) => {
      setActionError(getErrorMessage(err))
    },
  })

  const cancelMutation = useMutation({
    mutationFn: () => betsApi.cancel(betId!),
    onSuccess: (updated) => {
      queryClient.setQueryData(['bet', betId], updated)
      queryClient.invalidateQueries({ queryKey: ['bets'] })
      setActionError(null)
      setActionSuccess('Bet cancelled. Your stake has been refunded.')
    },
    onError: (err) => {
      setActionError(getErrorMessage(err))
    },
  })

  if (isLoading) return <PageSpinner />
  if (error)     return <ErrorMessage error={getErrorMessage(error)} />
  if (!bet)      return null

  const isCreator     = user?.id === bet.creator_id
  const isOpponent    = user?.id === bet.opponent_id
  const isParticipant = isCreator || isOpponent
  const canAccept     = bet.status === 'OPEN' && !isCreator
  const canCancel     = bet.status === 'OPEN' && isCreator
  const isBusy        = acceptMutation.isPending || cancelMutation.isPending

  const availablePredictions = ALL_PREDICTIONS.filter(
    (p) => p !== bet.creator_prediction,
  )

  // Settlement personalisation
  const isWinner    = isParticipant && user?.id === bet.winner_id
  const isNoWinner  = bet.settlement_outcome === 'no_winner'
  const isVoided    = bet.settlement_outcome === 'voided'

  function onAccept(data: { opponent_prediction: FootballOutcome }) {
    setActionError(null)
    setActionSuccess(null)
    acceptMutation.mutate(data.opponent_prediction)
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="text-gray-500 hover:text-gray-300">
          ←
        </button>
        <h1 className="text-xl font-bold text-white">Bet Detail</h1>
        <BetStatusBadge status={bet.status} />
      </div>

      {/* Match */}
      <Card>
        <CardHeader>
          <CardTitle>Match</CardTitle>
          <span className="text-sm text-gray-500">{bet.match.competition}</span>
        </CardHeader>
        <p className="text-lg font-semibold text-white">
          {bet.match.home_team} <span className="text-gray-500">vs</span> {bet.match.away_team}
        </p>
        <p className="mt-1 text-sm text-gray-400">
          Kick-off: {formatDate(bet.match.kickoff_at)}
        </p>
        {bet.match.outcome && (
          <p className="mt-2 text-sm font-medium text-brand-400">
            Result: {OUTCOME_LABELS[bet.match.outcome]}
            {bet.match.result_home_score != null && (
              <span className="ml-2 text-gray-300">
                ({bet.match.result_home_score}–{bet.match.result_away_score})
              </span>
            )}
          </p>
        )}
      </Card>

      {/* Bet details */}
      <Card>
        <CardHeader>
          <CardTitle>Bet Details</CardTitle>
          <span className="text-sm text-gray-500">
            Created {formatDate(bet.created_at)}
          </span>
        </CardHeader>

        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-gray-500">Stake</dt>
            <dd className="font-semibold text-brand-400">
              {formatMoney(bet.stake_amount, bet.currency)}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">Creator's pick</dt>
            <dd className="font-medium text-gray-200">
              {OUTCOME_LABELS[bet.creator_prediction]}
              {isCreator && <span className="ml-1 text-xs text-gray-500">(you)</span>}
            </dd>
          </div>
          {bet.opponent_prediction && (
            <div>
              <dt className="text-gray-500">Opponent's pick</dt>
              <dd className="font-medium text-gray-200">
                {OUTCOME_LABELS[bet.opponent_prediction]}
                {isOpponent && <span className="ml-1 text-xs text-gray-500">(you)</span>}
              </dd>
            </div>
          )}
          <div>
            <dt className="text-gray-500">Expires</dt>
            <dd className="text-gray-200">{formatDate(bet.expires_at)}</dd>
          </div>
        </dl>
      </Card>

      {/* Settlement */}
      {(bet.status === 'SETTLED' || bet.status === 'VOIDED') && (
        <Card>
          <CardHeader>
            <CardTitle>Settlement</CardTitle>
            {bet.settled_at && (
              <span className="text-sm text-gray-500">{formatDate(bet.settled_at)}</span>
            )}
          </CardHeader>

          {/* Personal outcome banner */}
          {isParticipant && bet.settlement_outcome && (
            <div
              className={[
                'mb-4 rounded-lg border px-4 py-3 text-center text-sm font-semibold',
                isWinner
                  ? 'border-green-700/50 bg-green-900/30 text-green-300'
                  : isNoWinner || isVoided
                  ? 'border-gray-700 bg-gray-800 text-gray-300'
                  : 'border-red-700/50 bg-red-900/20 text-red-300',
              ].join(' ')}
            >
              {isWinner
                ? `You won${bet.payout_amount ? ` — payout ${formatMoney(bet.payout_amount, bet.currency)}` : '!'}`
                : isNoWinner
                ? 'No winner — your stake has been refunded.'
                : isVoided
                ? 'Bet voided — your stake has been refunded.'
                : 'You lost this one. Better luck next time!'}
            </div>
          )}

          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-gray-500">Outcome</dt>
              <dd className="font-medium text-gray-200">
                {bet.settlement_outcome
                  ? SETTLEMENT_LABELS[bet.settlement_outcome]
                  : '—'}
              </dd>
            </div>
            {bet.payout_amount && (
              <div>
                <dt className="text-gray-500">Payout</dt>
                <dd className="font-semibold text-brand-400">
                  {formatMoney(bet.payout_amount, bet.currency)}
                </dd>
              </div>
            )}
            {bet.platform_fee && (
              <div>
                <dt className="text-gray-500">Platform fee</dt>
                <dd className="text-gray-300">
                  {formatMoney(bet.platform_fee, bet.currency)}
                </dd>
              </div>
            )}
            {bet.winner_id && (
              <div>
                <dt className="text-gray-500">Winner</dt>
                <dd className="font-mono text-xs text-gray-400 truncate">
                  {bet.winner_id === user?.id ? 'You' : bet.winner_id}
                </dd>
              </div>
            )}
          </dl>
        </Card>
      )}

      {/* Feedback */}
      {actionSuccess && <SuccessMessage message={actionSuccess} />}
      {actionError   && <ErrorMessage  error={actionError} />}

      {/* Accept form */}
      {canAccept && (
        <Card>
          <CardHeader>
            <CardTitle>Accept This Bet</CardTitle>
          </CardHeader>
          <form onSubmit={handleSubmit(onAccept)} className="space-y-4">
            <div>
              <p className="mb-2 text-sm text-gray-400">Choose your prediction:</p>
              <Controller
                name="opponent_prediction"
                control={control}
                rules={{ required: true }}
                render={({ field }) => (
                  <div className="grid grid-cols-3 gap-2">
                    {availablePredictions.map((pred) => (
                      <button
                        key={pred}
                        type="button"
                        disabled={isBusy}
                        onClick={() => field.onChange(pred)}
                        className={[
                          'rounded-lg border py-2.5 text-sm font-medium transition-colors',
                          'disabled:cursor-not-allowed disabled:opacity-50',
                          field.value === pred
                            ? 'border-brand-500 bg-brand-500/20 text-brand-300'
                            : 'border-gray-700 bg-gray-800 text-gray-300 hover:border-gray-500',
                        ].join(' ')}
                      >
                        {OUTCOME_LABELS[pred]}
                      </button>
                    ))}
                  </div>
                )}
              />
            </div>
            {formErrors.opponent_prediction && (
              <p className="text-xs text-red-400">Please select a prediction before confirming.</p>
            )}
            <Button
              type="submit"
              className="w-full"
              loading={acceptMutation.isPending}
              disabled={!chosenPrediction || isBusy}
            >
              Confirm — stake {formatMoney(bet.stake_amount, bet.currency)}
            </Button>
          </form>
        </Card>
      )}

      {/* Cancel */}
      {canCancel && (
        <div className="flex justify-end">
          <Button
            variant="danger"
            loading={cancelMutation.isPending}
            disabled={isBusy}
            onClick={() => {
              setActionError(null)
              setActionSuccess(null)
              cancelMutation.mutate()
            }}
          >
            Cancel Bet
          </Button>
        </div>
      )}
    </div>
  )
}
