import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { matchesApi } from '../api/matches'
import type { MatchStatus } from '../api/types'
import { MatchCard } from '../components/match/MatchCard'
import { Pagination } from '../components/ui/Pagination'
import { Button } from '../components/ui/Button'
import { PageSpinner } from '../components/ui/Spinner'
import { ErrorMessage } from '../components/ui/ErrorMessage'
import { getErrorMessage } from '../utils/errors'

// ── Filter tabs ─────────────────────────────────────────────────────────────

type StatusTab = 'upcoming' | 'all' | 'completed'

const STATUS_TABS: { id: StatusTab; label: string; value: MatchStatus | undefined }[] = [
  { id: 'upcoming',  label: 'Upcoming',  value: 'scheduled' },
  { id: 'all',       label: 'All',       value: undefined   },
  { id: 'completed', label: 'Completed', value: 'completed' },
]

// ── Page ────────────────────────────────────────────────────────────────────

export default function MatchesPage() {
  const [page, setPage] = useState(1)
  const [activeTab, setActiveTab] = useState<StatusTab>('upcoming')
  const [competitionInput, setCompetitionInput] = useState('')
  const [appliedCompetition, setAppliedCompetition] = useState('')

  const statusValue = STATUS_TABS.find((t) => t.id === activeTab)?.value

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['matches', page, activeTab, appliedCompetition],
    queryFn: () =>
      matchesApi.list({
        page,
        status: statusValue,
        competition: appliedCompetition || undefined,
      }),
  })

  function handleTabChange(tab: StatusTab) {
    setActiveTab(tab)
    setPage(1)
  }

  function handleCompetitionSearch(e: React.FormEvent) {
    e.preventDefault()
    setAppliedCompetition(competitionInput.trim())
    setPage(1)
  }

  function clearCompetitionFilter() {
    setCompetitionInput('')
    setAppliedCompetition('')
    setPage(1)
  }

  // ── Empty-state message depends on active filters ────────────────────────
  function emptyMessage() {
    if (appliedCompetition) {
      return `No ${activeTab === 'upcoming' ? 'upcoming ' : ''}matches found for "${appliedCompetition}".`
    }
    if (activeTab === 'upcoming') return 'No upcoming matches right now. Check back later.'
    if (activeTab === 'completed') return 'No completed matches yet.'
    return 'No matches found.'
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Matches</h1>
          <p className="mt-1 text-sm text-gray-400">
            Browse upcoming fixtures and create bets.
          </p>
        </div>
        {isFetching && !isLoading && (
          <span className="text-xs text-gray-500">Refreshing…</span>
        )}
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
        {/* Status tabs */}
        <div className="flex rounded-lg border border-gray-700 bg-gray-800 p-0.5">
          {STATUS_TABS.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => handleTabChange(id)}
              className={[
                'flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                activeTab === id
                  ? 'bg-brand-500 text-white'
                  : 'text-gray-400 hover:text-white',
              ].join(' ')}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Competition filter */}
        <form onSubmit={handleCompetitionSearch} className="flex items-center gap-2">
          <input
            type="text"
            value={competitionInput}
            onChange={(e) => setCompetitionInput(e.target.value)}
            placeholder="Filter by competition…"
            className="flex-1 rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-100 placeholder-gray-500 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 sm:flex-none"
          />
          {appliedCompetition ? (
            <Button type="button" variant="ghost" size="sm" onClick={clearCompetitionFilter}>
              Clear
            </Button>
          ) : (
            <Button type="submit" variant="secondary" size="sm" disabled={!competitionInput.trim()}>
              Search
            </Button>
          )}
        </form>
      </div>

      {/* States */}
      {isLoading && <PageSpinner />}

      {!isLoading && error && (
        <div className="space-y-2">
          <ErrorMessage error={getErrorMessage(error)} />
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      )}

      {!isLoading && !error && data && (
        <>
          {data.items.length === 0 ? (
            <p className="py-12 text-center text-gray-500">{emptyMessage()}</p>
          ) : (
            <div className="space-y-3">
              {data.items.map((match) => (
                <MatchCard key={match.id} match={match} />
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
