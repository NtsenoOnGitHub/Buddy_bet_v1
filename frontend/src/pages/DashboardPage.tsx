import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { betsApi } from '../api/bets'
import { BetCard } from '../components/bet/BetCard'
import { Pagination } from '../components/ui/Pagination'
import { Button } from '../components/ui/Button'
import { PageSpinner } from '../components/ui/Spinner'
import { ErrorMessage } from '../components/ui/ErrorMessage'
import { getErrorMessage } from '../utils/errors'

export default function DashboardPage() {
  const [page, setPage] = useState(1)

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['bets', 'open', page],
    queryFn: () => betsApi.listOpen(page),
  })

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Open Bets</h1>
          <p className="mt-1 text-sm text-gray-400">
            Browse and accept bets from other players.
          </p>
        </div>
        {isFetching && !isLoading && (
          <span className="text-xs text-gray-500">Refreshing…</span>
        )}
      </div>

      {isLoading && <PageSpinner />}

      {error && (
        <div className="space-y-2">
          <ErrorMessage error={getErrorMessage(error)} />
          <Button variant="secondary" size="sm" onClick={() => refetch()}>Retry</Button>
        </div>
      )}

      {data && (
        <>
          {data.items.length === 0 ? (
            <p className="py-12 text-center text-gray-500">No open bets right now. Be the first to place one!</p>
          ) : (
            <div className="space-y-3">
              {data.items.map((bet) => (
                <BetCard key={bet.id} bet={bet} showAccept />
              ))}
            </div>
          )}

          <Pagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  )
}
