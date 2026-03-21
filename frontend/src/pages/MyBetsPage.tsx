import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { betsApi } from '../api/bets'
import type { BetStatus } from '../api/types'
import { BetCard } from '../components/bet/BetCard'
import { Pagination } from '../components/ui/Pagination'
import { PageSpinner } from '../components/ui/Spinner'
import { ErrorMessage } from '../components/ui/ErrorMessage'
import { getErrorMessage } from '../utils/errors'

const TABS: { label: string; value: BetStatus | undefined }[] = [
  { label: 'All',       value: undefined },
  { label: 'Open',      value: 'OPEN' },
  { label: 'Matched',   value: 'MATCHED' },
  { label: 'Settled',   value: 'SETTLED' },
  { label: 'Cancelled', value: 'CANCELLED' },
]

export default function MyBetsPage() {
  const [page, setPage]       = useState(1)
  const [activeTab, setActiveTab] = useState<BetStatus | undefined>(undefined)

  function handleTabChange(val: BetStatus | undefined) {
    setActiveTab(val)
    setPage(1)
  }

  const { data, isLoading, error } = useQuery({
    queryKey: ['bets', 'my', activeTab, page],
    queryFn: () => betsApi.listMy(page, 20, activeTab),
  })

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">My Bets</h1>
        <p className="mt-1 text-sm text-gray-400">
          All bets where you are the creator or the opponent.
        </p>
      </div>

      {/* Status tabs */}
      <div className="mb-5 flex gap-1 overflow-x-auto rounded-lg border border-gray-800 bg-gray-900 p-1">
        {TABS.map((tab) => (
          <button
            key={tab.label}
            onClick={() => handleTabChange(tab.value)}
            className={[
              'rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap transition-colors',
              activeTab === tab.value
                ? 'bg-gray-700 text-white'
                : 'text-gray-400 hover:text-white',
            ].join(' ')}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {isLoading && <PageSpinner />}
      {error && <ErrorMessage error={getErrorMessage(error)} />}

      {data && (
        <>
          {data.items.length === 0 ? (
            <p className="text-gray-500">No bets found.</p>
          ) : (
            <div className="space-y-3">
              {data.items.map((bet) => (
                <BetCard key={bet.id} bet={bet} />
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
