/**
 * DepositReturnPage — shown when the user returns from PayFast.
 *
 * PayFast redirects to /wallet/deposit/return?deposit_id=<uuid>
 * (or /wallet/deposit/cancel?deposit_id=<uuid> on cancellation).
 *
 * This page fetches the deposit status from the backend.  It does NOT assume
 * the payment was successful based on the URL — the authoritative state comes
 * from the server, which is updated only after a verified ITN webhook.
 *
 * Polling: we poll every 3 seconds for up to 30 seconds while the deposit is
 * still in processing state.  After that we show the last known status and
 * invite the user to refresh manually.
 */
import { useEffect, useRef, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { depositsApi } from '../api/deposits'
import type { DepositResponse, DepositStatus } from '../api/types'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import { PageSpinner } from '../components/ui/Spinner'
import { formatMoney } from '../utils/money'
import { formatDate } from '../utils/date'
import { getErrorMessage } from '../utils/errors'

type BadgeVariant = 'green' | 'blue' | 'yellow' | 'red' | 'gray'

const DEPOSIT_STATUS_VARIANT: Record<DepositStatus, BadgeVariant> = {
  pending:    'yellow',
  processing: 'blue',
  completed:  'green',
  failed:     'red',
  cancelled:  'gray',
}

const DEPOSIT_STATUS_LABEL: Record<DepositStatus, string> = {
  pending:    'Pending',
  processing: 'Processing',
  completed:  'Completed',
  failed:     'Failed',
  cancelled:  'Cancelled',
}

const POLL_INTERVAL_MS = 3000
const MAX_POLLS = 10  // 30 s max polling window

export default function DepositReturnPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const depositId = searchParams.get('deposit_id')
  const isCancelUrl = window.location.pathname.includes('/cancel')

  const [deposit, setDeposit] = useState<DepositResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [pollCount, setPollCount] = useState(0)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function fetchDeposit() {
    if (!depositId) return
    try {
      const d = await depositsApi.get(depositId)
      setDeposit(d)
      setError(null)
      return d
    } catch (err) {
      setError(getErrorMessage(err))
      return null
    } finally {
      setIsLoading(false)
    }
  }

  // Initial fetch + polling while processing
  useEffect(() => {
    if (!depositId) {
      setIsLoading(false)
      setError('No deposit reference found in the URL.')
      return
    }

    fetchDeposit().then((d) => {
      if (!d) return
      // Start polling if still processing
      if (d.status === 'processing' || d.status === 'pending') {
        intervalRef.current = setInterval(async () => {
          setPollCount((c) => {
            if (c >= MAX_POLLS - 1) {
              clearInterval(intervalRef.current!)
              return c
            }
            return c + 1
          })
          const updated = await fetchDeposit()
          if (updated && updated.status !== 'processing' && updated.status !== 'pending') {
            clearInterval(intervalRef.current!)
          }
        }, POLL_INTERVAL_MS)
      }
    })

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [depositId])

  async function handleManualRefresh() {
    setIsRefreshing(true)
    await fetchDeposit()
    setIsRefreshing(false)
  }

  // No deposit_id in URL
  if (!depositId) {
    return (
      <div className="mx-auto max-w-lg">
        <Card>
          <p className="text-center text-gray-400">
            No deposit reference found. Please check your deposit history.
          </p>
          <div className="mt-4 flex justify-center">
            <Button onClick={() => navigate('/wallet')}>Go to Wallet</Button>
          </div>
        </Card>
      </div>
    )
  }

  if (isLoading) return <PageSpinner />

  if (error && !deposit) {
    return (
      <div className="mx-auto max-w-lg">
        <Card>
          <p className="text-center text-red-400">{error}</p>
          <div className="mt-4 flex justify-center gap-3">
            <Button variant="secondary" onClick={handleManualRefresh} loading={isRefreshing}>
              Retry
            </Button>
            <Button onClick={() => navigate('/wallet')}>Go to Wallet</Button>
          </div>
        </Card>
      </div>
    )
  }

  if (!deposit) return null

  const isTerminal = ['completed', 'failed', 'cancelled'].includes(deposit.status)
  const isPolling = !isTerminal && pollCount < MAX_POLLS

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Deposit Status</h1>
        <p className="mt-1 text-sm text-gray-400">
          {isCancelUrl && deposit.status !== 'completed'
            ? 'You cancelled the payment.'
            : 'Your payment is being processed.'}
        </p>
      </div>

      <Card>
        <div className="space-y-4">
          {/* Status */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-400">Status</span>
            <Badge variant={DEPOSIT_STATUS_VARIANT[deposit.status]}>
              {DEPOSIT_STATUS_LABEL[deposit.status]}
            </Badge>
          </div>

          {/* Amount */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-400">Amount</span>
            <span className="font-semibold text-white">
              {formatMoney(deposit.amount, deposit.currency)}
            </span>
          </div>

          {/* Provider */}
          {deposit.payment_provider && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-400">Provider</span>
              <span className="text-sm capitalize text-gray-300">{deposit.payment_provider}</span>
            </div>
          )}

          {/* Reference */}
          {deposit.provider_reference && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-400">Reference</span>
              <span className="font-mono text-xs text-gray-400">{deposit.provider_reference}</span>
            </div>
          )}

          {/* Date */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-400">Requested</span>
            <span className="text-sm text-gray-300">{formatDate(deposit.requested_at)}</span>
          </div>

          {deposit.completed_at && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-400">Completed</span>
              <span className="text-sm text-gray-300">{formatDate(deposit.completed_at)}</span>
            </div>
          )}

          {/* Status-specific messages */}
          {deposit.status === 'completed' && (
            <div className="rounded-lg border border-green-700/40 bg-green-900/20 px-4 py-3">
              <p className="text-sm font-medium text-green-300">
                Payment confirmed — your wallet has been credited.
              </p>
            </div>
          )}

          {deposit.status === 'processing' && (
            <div className="rounded-lg border border-blue-700/40 bg-blue-900/20 px-4 py-3">
              <p className="text-sm text-blue-300">
                {isPolling
                  ? 'Waiting for payment confirmation from PayFast\u2026'
                  : 'Payment confirmation is taking longer than usual. Your wallet will update once confirmed.'}
              </p>
              {isPolling && (
                <p className="mt-1 text-xs text-blue-400">Auto-refreshing every 3 seconds.</p>
              )}
            </div>
          )}

          {(deposit.status === 'failed' || deposit.status === 'cancelled') && (
            <div className="rounded-lg border border-red-700/40 bg-red-900/20 px-4 py-3">
              <p className="text-sm text-red-300">
                {deposit.status === 'cancelled'
                  ? 'Payment was cancelled. No funds have been taken from your account.'
                  : 'Payment failed. No funds have been taken from your account.'}
              </p>
            </div>
          )}
        </div>
      </Card>

      {/* Actions */}
      <div className="flex gap-3">
        {!isTerminal && !isPolling && (
          <Button
            variant="secondary"
            className="flex-1"
            onClick={handleManualRefresh}
            loading={isRefreshing}
          >
            Refresh status
          </Button>
        )}
        <Button className="flex-1" onClick={() => navigate('/wallet')}>
          Go to Wallet
        </Button>
        {(deposit.status === 'failed' || deposit.status === 'cancelled') && (
          <Button
            variant="secondary"
            className="flex-1"
            onClick={() => navigate('/wallet/deposit')}
          >
            Try again
          </Button>
        )}
      </div>
    </div>
  )
}
