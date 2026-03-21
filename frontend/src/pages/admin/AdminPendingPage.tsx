import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '../../api/admin'
import type { PendingSettlementItem } from '../../api/types'
import { Card } from '../../components/ui/Card'
import { Button } from '../../components/ui/Button'
import { Badge } from '../../components/ui/Badge'
import { ErrorMessage } from '../../components/ui/ErrorMessage'
import { SuccessMessage } from '../../components/ui/SuccessMessage'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { PageSpinner } from '../../components/ui/Spinner'
import { formatMoney } from '../../utils/money'
import { formatDate, formatPendingAge } from '../../utils/date'
import { getErrorMessage } from '../../utils/errors'

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-gray-800 bg-gray-900/40 py-16 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-green-900/40">
        <svg
          className="h-6 w-6 text-green-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </div>
      <p className="text-sm font-medium text-gray-200">All clear</p>
      <p className="mt-1 text-xs text-gray-500">No bets are pending settlement right now.</p>
    </div>
  )
}

// ── Bet row ───────────────────────────────────────────────────────────────────

interface BetRowProps {
  item: PendingSettlementItem
  successMsg: string
  errorMsg: string
  isSettling: boolean
  isVoiding: boolean
  voidingActive: boolean   // this row's void form is open
  voidReason: string
  onRetryClick: () => void
  onVoidOpen: () => void
  onVoidReasonChange: (v: string) => void
  onVoidSubmit: () => void
  onVoidCancel: () => void
}

function BetRow({
  item,
  successMsg,
  errorMsg,
  isSettling,
  isVoiding,
  voidingActive,
  voidReason,
  onRetryClick,
  onVoidOpen,
  onVoidReasonChange,
  onVoidSubmit,
  onVoidCancel,
}: BetRowProps) {
  const isDone     = !!successMsg
  const pendingAge = formatPendingAge(item.updated_at)

  return (
    <Card>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        {/* Info */}
        <div className="min-w-0 space-y-1 text-sm">
          <p className="truncate font-mono text-xs text-gray-500">Bet: {item.id}</p>
          <p className="truncate font-mono text-xs text-gray-500">Match: {item.match_id}</p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-0.5">
            <span className="font-semibold text-brand-400">
              {formatMoney(item.stake_amount, item.currency)}
            </span>
            {item.updated_at && (
              <span className="text-xs text-gray-500">
                Since {formatDate(item.updated_at)}
                {pendingAge && (
                  <span className="ml-1 font-medium text-yellow-500">({pendingAge})</span>
                )}
              </span>
            )}
          </div>
        </div>

        {/* Actions */}
        {!isDone && (
          <div className="flex shrink-0 gap-2">
            <Button
              size="sm"
              variant="secondary"
              loading={isSettling}
              disabled={voidingActive || isVoiding}
              onClick={onRetryClick}
            >
              Retry Settlement
            </Button>
            {!voidingActive && (
              <Button
                size="sm"
                variant="danger"
                disabled={isSettling}
                onClick={onVoidOpen}
              >
                Void
              </Button>
            )}
          </div>
        )}
      </div>

      {/* Inline void reason form */}
      {voidingActive && (
        <div className="mt-3 space-y-2 border-t border-gray-800 pt-3">
          <label className="text-xs font-medium text-gray-300">
            Reason for voiding (required)
          </label>
          <textarea
            className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            rows={2}
            placeholder="Enter a reason…"
            value={voidReason}
            onChange={(e) => onVoidReasonChange(e.target.value)}
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="danger"
              disabled={!voidReason.trim() || isVoiding}
              onClick={onVoidSubmit}
            >
              Confirm Void
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={isVoiding}
              onClick={onVoidCancel}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      {successMsg && (
        <div className="mt-2">
          <SuccessMessage message={successMsg} />
        </div>
      )}
      {errorMsg && (
        <div className="mt-2">
          <ErrorMessage error={errorMsg} />
        </div>
      )}
    </Card>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AdminPendingPage() {
  const queryClient = useQueryClient()

  // Per-bet feedback
  const [betErrors,  setBetErrors]  = useState<Record<string, string>>({})
  const [betSuccess, setBetSuccess] = useState<Record<string, string>>({})

  // Void form state (one at a time)
  const [voidingId,     setVoidingId]     = useState<string | null>(null)
  const [voidReason,    setVoidReason]    = useState('')

  // Confirmation dialogs
  const [retryConfirmId, setRetryConfirmId] = useState<string | null>(null)
  const [voidConfirmId,  setVoidConfirmId]  = useState<string | null>(null)

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
        [betId]: [
          'Settled successfully',
          result.settlement_outcome
            ? `— ${result.settlement_outcome.replace(/_/g, ' ')}`
            : null,
          result.payout_amount
            ? `· Payout: ${result.payout_amount}`
            : null,
        ]
          .filter(Boolean)
          .join(' '),
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
      setBetSuccess((p) => ({
        ...p,
        [betId]: result.message || `Voided — ${result.refunded_user_ids.length} participant(s) refunded.`,
      }))
      setVoidingId(null)
      setVoidReason('')
      queryClient.invalidateQueries({ queryKey: ['admin', 'pending'] })
    },
    onError: (err, { betId }) => {
      setBetErrors((p) => ({ ...p, [betId]: getErrorMessage(err) }))
    },
  })

  // Items needed for dialog descriptions
  const retryItem = retryConfirmId
    ? data?.items.find((i) => i.id === retryConfirmId)
    : undefined
  const voidItem = voidConfirmId
    ? data?.items.find((i) => i.id === voidConfirmId)
    : undefined

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Pending Settlement</h1>
          <p className="mt-1 text-sm text-gray-400">
            Bets stuck in PENDING_SETTLEMENT — retry or void individually.
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

      {data && data.items.length === 0 && <EmptyState />}

      {data && data.items.length > 0 && (
        <div className="space-y-3">
          {data.items.map((item) => {
            const isSettling = settleMutation.isPending && settleMutation.variables === item.id
            const isVoiding  = voidMutation.isPending && voidMutation.variables?.betId === item.id

            return (
              <BetRow
                key={item.id}
                item={item}
                successMsg={betSuccess[item.id] ?? ''}
                errorMsg={betErrors[item.id] ?? ''}
                isSettling={isSettling}
                isVoiding={isVoiding}
                voidingActive={voidingId === item.id}
                voidReason={voidReason}
                onRetryClick={() => {
                  setBetErrors((p) => ({ ...p, [item.id]: '' }))
                  setRetryConfirmId(item.id)
                }}
                onVoidOpen={() => {
                  setVoidingId(item.id)
                  setVoidReason('')
                }}
                onVoidReasonChange={setVoidReason}
                onVoidSubmit={() => setVoidConfirmId(item.id)}
                onVoidCancel={() => {
                  setVoidingId(null)
                  setVoidReason('')
                }}
              />
            )
          })}
        </div>
      )}

      {/* Retry settlement confirmation */}
      <ConfirmDialog
        open={!!retryConfirmId}
        title="Retry settlement?"
        description={
          retryItem
            ? `Retry settlement for bet ${retryConfirmId!.slice(0, 8)}… (${formatMoney(retryItem.stake_amount, retryItem.currency)}). The system will attempt to process this bet again.`
            : 'Retry settlement for this bet?'
        }
        confirmLabel="Retry"
        loading={settleMutation.isPending}
        onConfirm={() => {
          const id = retryConfirmId!
          setRetryConfirmId(null)
          settleMutation.mutate(id)
        }}
        onCancel={() => setRetryConfirmId(null)}
      />

      {/* Void confirmation */}
      <ConfirmDialog
        open={!!voidConfirmId}
        title="Void this bet?"
        description={
          voidItem
            ? `Void bet ${voidConfirmId!.slice(0, 8)}… (${formatMoney(voidItem.stake_amount, voidItem.currency)}) and refund all participants.\n\nReason: "${voidReason}"`
            : 'This will void the bet and refund all participants.'
        }
        confirmLabel="Void Bet"
        destructive
        loading={voidMutation.isPending}
        onConfirm={() => {
          const id = voidConfirmId!
          setVoidConfirmId(null)
          voidMutation.mutate({ betId: id, reason: voidReason })
        }}
        onCancel={() => setVoidConfirmId(null)}
      />
    </div>
  )
}
