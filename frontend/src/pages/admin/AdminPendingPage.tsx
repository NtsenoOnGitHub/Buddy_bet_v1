import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '../../api/admin'
import { Card } from '../../components/ui/Card'
import { Button } from '../../components/ui/Button'
import { Badge } from '../../components/ui/Badge'
import { ErrorMessage } from '../../components/ui/ErrorMessage'
import { SuccessMessage } from '../../components/ui/SuccessMessage'
import { PageSpinner } from '../../components/ui/Spinner'
import { formatMoney } from '../../utils/money'
import { formatDate } from '../../utils/date'
import { getErrorMessage } from '../../utils/errors'

export default function AdminPendingPage() {
  const queryClient = useQueryClient()

  // Per-bet feedback state
  const [betErrors, setBetErrors]   = useState<Record<string, string>>({})
  const [betSuccess, setBetSuccess] = useState<Record<string, string>>({})

  // Void form state
  const [voidingId, setVoidingId]   = useState<string | null>(null)
  const [voidReason, setVoidReason] = useState('')

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['admin', 'pending'],
    queryFn: () => adminApi.listPending(),
  })

  const settleMutation = useMutation({
    mutationFn: (betId: string) => adminApi.settleBet(betId),
    onSuccess: (result, betId) => {
      setBetErrors((p) => ({ ...p, [betId]: '' }))
      setBetSuccess((p) => ({
        ...p,
        [betId]: `Settled — ${result.settlement_outcome ?? 'done'}.${result.payout_amount ? ` Payout: ${result.payout_amount}` : ''}`,
      }))
      queryClient.invalidateQueries({ queryKey: ['admin', 'pending'] })
    },
    onError: (err, betId) => {
      setBetErrors((p) => ({ ...p, [betId]: getErrorMessage(err) }))
    },
  })

  const voidMutation = useMutation({
    mutationFn: ({ betId, reason }: { betId: string; reason: string }) =>
      adminApi.voidBet(betId, reason),
    onSuccess: (result, { betId }) => {
      setBetErrors((p) => ({ ...p, [betId]: '' }))
      setBetSuccess((p) => ({ ...p, [betId]: result.message }))
      setVoidingId(null)
      setVoidReason('')
      queryClient.invalidateQueries({ queryKey: ['admin', 'pending'] })
    },
    onError: (err, { betId }) => {
      setBetErrors((p) => ({ ...p, [betId]: getErrorMessage(err) }))
    },
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Pending Settlement</h1>
          <p className="mt-1 text-sm text-gray-400">
            Bets stuck in PENDING_SETTLEMENT — retry settlement or void individually.
          </p>
        </div>
        {data && (
          <Badge variant={data.total > 0 ? 'yellow' : 'green'}>
            {data.total} pending
          </Badge>
        )}
      </div>

      {isLoading && <PageSpinner />}

      {error && (
        <div className="space-y-2">
          <ErrorMessage error={getErrorMessage(error)} />
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      )}

      {data && data.items.length === 0 && (
        <p className="py-12 text-center text-gray-500">No bets pending settlement. All clear.</p>
      )}

      {data && data.items.length > 0 && (
        <div className="space-y-3">
          {data.items.map((item) => {
            const isSettling = settleMutation.isPending && settleMutation.variables === item.id
            const isVoiding  = voidMutation.isPending && voidMutation.variables?.betId === item.id
            const isDone     = !!betSuccess[item.id]

            return (
              <Card key={item.id}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="space-y-1 text-sm">
                    <p className="font-mono text-xs text-gray-500 truncate">Bet: {item.id}</p>
                    <p className="font-mono text-xs text-gray-500 truncate">Match: {item.match_id}</p>
                    <div className="flex items-center gap-4 pt-0.5">
                      <span className="font-semibold text-brand-400">
                        {formatMoney(item.stake_amount, item.currency)}
                      </span>
                      {item.updated_at && (
                        <span className="text-xs text-gray-500">
                          Pending since {formatDate(item.updated_at)}
                        </span>
                      )}
                    </div>
                  </div>

                  {!isDone && (
                    <div className="flex shrink-0 gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={isSettling}
                        disabled={voidingId === item.id || isVoiding}
                        onClick={() => {
                          setBetErrors((p) => ({ ...p, [item.id]: '' }))
                          settleMutation.mutate(item.id)
                        }}
                      >
                        Retry Settlement
                      </Button>
                      {voidingId !== item.id && (
                        <Button
                          size="sm"
                          variant="danger"
                          disabled={isSettling}
                          onClick={() => { setVoidingId(item.id); setVoidReason('') }}
                        >
                          Void
                        </Button>
                      )}
                    </div>
                  )}
                </div>

                {/* Inline void form */}
                {voidingId === item.id && (
                  <div className="mt-3 space-y-2 border-t border-gray-800 pt-3">
                    <label className="text-xs font-medium text-gray-300">
                      Reason for voiding (required)
                    </label>
                    <textarea
                      className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                      rows={2}
                      placeholder="Enter a reason…"
                      value={voidReason}
                      onChange={(e) => setVoidReason(e.target.value)}
                    />
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="danger"
                        loading={isVoiding}
                        disabled={!voidReason.trim()}
                        onClick={() =>
                          voidMutation.mutate({ betId: item.id, reason: voidReason })
                        }
                      >
                        Confirm Void
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={isVoiding}
                        onClick={() => { setVoidingId(null); setVoidReason('') }}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}

                {betSuccess[item.id] && (
                  <div className="mt-2">
                    <SuccessMessage message={betSuccess[item.id]} />
                  </div>
                )}
                {betErrors[item.id] && (
                  <div className="mt-2">
                    <ErrorMessage error={betErrors[item.id]} />
                  </div>
                )}
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
