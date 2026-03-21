import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { betsApi } from '../api/bets'
import { BetCard } from '../components/bet/BetCard'
import { Pagination } from '../components/ui/Pagination'
import { PageSpinner } from '../components/ui/Spinner'
import { ErrorMessage } from '../components/ui/ErrorMessage'
import { getErrorMessage } from '../utils/errors'

export default function DashboardPage() {
  const [page, setPage] = useState(1)

  const { data, isLoading, error } = useQuery({
    queryKey: ['bets', 'open', page],
    queryFn: () => betsApi.listOpen(page),
  })

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Open Bets</h1>
        <p className="mt-1 text-sm text-gray-400">
          Browse and accept bets from other players.
        </p>
      </div>

      {isLoading && <PageSpinner />}

      {error && <ErrorMessage error={getErrorMessage(error)} />}

      {data && (
        <>
          {data.items.length === 0 ? (
            <p className="text-gray-500">No open bets yet.</p>
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
