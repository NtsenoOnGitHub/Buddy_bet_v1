import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { walletApi } from '../api/wallet'
import { depositsApi } from '../api/deposits'
import type { DepositStatus, LedgerEntryType } from '../api/types'
import { Card, CardHeader, CardTitle } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Pagination } from '../components/ui/Pagination'
import { Button } from '../components/ui/Button'
import { PageSpinner } from '../components/ui/Spinner'
import { ErrorMessage } from '../components/ui/ErrorMessage'
import { formatMoney } from '../utils/money'
import { formatDate } from '../utils/date'
import { getErrorMessage } from '../utils/errors'

const ENTRY_LABELS: Record<LedgerEntryType, string> = {
  STAKE_LOCK:         'Bet placed',
  STAKE_UNLOCK:       'Bet cancelled',
  VOID_REFUND:        'Bet voided',
  SETTLEMENT_DEDUCT:  'Stake settled',
  FEE_DEDUCT:         'Platform fee',
  PAYOUT_CREDIT:      'Winnings',
  REFUND_CREDIT:      'Refund',
  DEPOSIT:            'Deposit',
  WITHDRAWAL:         'Withdrawal',
  WITHDRAWAL_HOLD:    'Withdrawal held',
  WITHDRAWAL_RELEASE: 'Withdrawal released',
}

type DepositBadgeVariant = 'green' | 'blue' | 'yellow' | 'red' | 'gray'

const DEPOSIT_STATUS_VARIANT: Record<DepositStatus, DepositBadgeVariant> = {
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

export default function WalletPage() {
  const [txPage, setTxPage] = useState(1)
  const [depositPage, setDepositPage] = useState(1)

  const {
    data: wallet,
    isLoading: walletLoading,
    error: walletError,
    refetch: refetchWallet,
  } = useQuery({
    queryKey: ['wallet'],
    queryFn: walletApi.get,
  })

  const {
    data: txData,
    isLoading: txLoading,
    error: txError,
    refetch: refetchTx,
  } = useQuery({
    queryKey: ['wallet', 'transactions', txPage],
    queryFn: () => walletApi.transactions(txPage),
  })

  const {
    data: depositData,
    isLoading: depositLoading,
    error: depositError,
    refetch: refetchDeposits,
  } = useQuery({
    queryKey: ['wallet', 'deposits', depositPage],
    queryFn: () => depositsApi.list(depositPage),
  })

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Wallet</h1>
          <p className="mt-1 text-sm text-gray-400">
            Your balances, deposits, and transaction history.
          </p>
        </div>
        <Link to="/wallet/deposit">
          <Button>Deposit</Button>
        </Link>
      </div>

      {/* Balance cards */}
      {walletLoading && <PageSpinner />}
      {walletError && (
        <div className="space-y-2">
          <ErrorMessage error={getErrorMessage(walletError)} />
          <Button variant="secondary" size="sm" onClick={() => refetchWallet()}>Retry</Button>
        </div>
      )}
      {wallet && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            { label: 'Available',   value: wallet.available_balance, highlight: true },
            { label: 'Locked',      value: wallet.locked_balance },
            { label: 'Total',       value: wallet.total_balance },
          ].map(({ label, value, highlight }) => (
            <Card key={label} className="text-center">
              <p className="text-xs text-gray-500">{label}</p>
              <p className={['mt-1 text-xl font-bold', highlight ? 'text-brand-400' : 'text-white'].join(' ')}>
                {formatMoney(value, wallet.currency)}
              </p>
            </Card>
          ))}
        </div>
      )}

      {/* Deposit history */}
      <Card>
        <CardHeader>
          <CardTitle>Deposits</CardTitle>
        </CardHeader>

        {depositLoading && <PageSpinner />}
        {depositError && (
          <div className="space-y-2">
            <ErrorMessage error={getErrorMessage(depositError)} />
            <Button variant="secondary" size="sm" onClick={() => refetchDeposits()}>Retry</Button>
          </div>
        )}

        {depositData && (
          <>
            {depositData.items.length === 0 ? (
              <div className="py-4 text-center">
                <p className="text-gray-500">No deposits yet.</p>
                <Link to="/wallet/deposit" className="mt-2 inline-block">
                  <Button size="sm" className="mt-2">Make your first deposit</Button>
                </Link>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-800 text-left text-xs text-gray-500">
                      <th className="pb-2 pr-4">Amount</th>
                      <th className="pb-2 pr-4">Status</th>
                      <th className="pb-2 pr-4">Provider</th>
                      <th className="pb-2">Date</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800">
                    {depositData.items.map((d) => (
                      <tr key={d.id} className="text-gray-300">
                        <td className="py-3 pr-4 font-semibold text-white">
                          {formatMoney(d.amount, d.currency)}
                        </td>
                        <td className="py-3 pr-4">
                          <Badge variant={DEPOSIT_STATUS_VARIANT[d.status]}>
                            {DEPOSIT_STATUS_LABEL[d.status]}
                          </Badge>
                          {(d.status === 'processing' || d.status === 'pending') && (
                            <Link
                              to={`/wallet/deposit/return?deposit_id=${d.id}`}
                              className="ml-2 text-xs text-brand-400 underline hover:text-brand-300"
                            >
                              Check status
                            </Link>
                          )}
                        </td>
                        <td className="py-3 pr-4 text-xs capitalize text-gray-500">
                          {d.payment_provider ?? '—'}
                        </td>
                        <td className="py-3 text-xs text-gray-500">
                          {formatDate(d.requested_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <Pagination
              page={depositData.page}
              pages={depositData.pages}
              total={depositData.total}
              onPageChange={setDepositPage}
            />
          </>
        )}
      </Card>

      {/* Transaction history */}
      <Card>
        <CardHeader>
          <CardTitle>Transactions</CardTitle>
        </CardHeader>

        {txLoading && <PageSpinner />}
        {txError && (
          <div className="space-y-2">
            <ErrorMessage error={getErrorMessage(txError)} />
            <Button variant="secondary" size="sm" onClick={() => refetchTx()}>Retry</Button>
          </div>
        )}

        {txData && (
          <>
            {txData.items.length === 0 ? (
              <p className="text-gray-500">No transactions yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-800 text-left text-xs text-gray-500">
                      <th className="pb-2 pr-4">Type</th>
                      <th className="pb-2 pr-4">Amount</th>
                      <th className="pb-2 pr-4">Balance after</th>
                      <th className="pb-2">Date</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800">
                    {txData.items.map((tx) => (
                      <tr key={tx.id} className="text-gray-300">
                        <td className="py-3 pr-4">
                          <div className="font-medium text-gray-100">
                            {ENTRY_LABELS[tx.entry_type] ?? tx.entry_type}
                          </div>
                          {tx.notes && (
                            <div className="mt-0.5 text-xs text-gray-500 truncate max-w-[200px]">
                              {tx.notes}
                            </div>
                          )}
                        </td>
                        <td className="py-3 pr-4">
                          <span
                            className={
                              tx.direction === 'credit'
                                ? 'text-brand-400'
                                : 'text-red-400'
                            }
                          >
                            {tx.direction === 'credit' ? '+' : '−'}
                            {formatMoney(tx.amount, wallet?.currency)}
                          </span>
                        </td>
                        <td className="py-3 pr-4 text-gray-400">
                          {tx.balance_field === 'available'
                            ? formatMoney(tx.available_balance_after, wallet?.currency)
                            : formatMoney(tx.locked_balance_after, wallet?.currency)}
                          <span className="ml-1 text-xs text-gray-600">
                            {tx.balance_field}
                          </span>
                        </td>
                        <td className="py-3 text-xs text-gray-500">
                          {formatDate(tx.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <Pagination
              page={txData.page}
              pages={txData.pages}
              total={txData.total}
              onPageChange={setTxPage}
            />
          </>
        )}
      </Card>
    </div>
  )
}
