import { useNavigate } from 'react-router-dom'
import { Card } from '../ui/Card'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { formatDate, formatRelative } from '../../utils/date'
import type { MatchResponse, MatchStatus } from '../../api/types'

// ── Status display config ───────────────────────────────────────────────────

const STATUS_LABELS: Record<MatchStatus, string> = {
  scheduled: 'Upcoming',
  live:      'Live',
  completed: 'Full Time',
  postponed: 'Postponed',
  cancelled: 'Cancelled',
  abandoned: 'Abandoned',
}

const STATUS_VARIANTS: Record<MatchStatus, 'green' | 'blue' | 'purple' | 'yellow' | 'gray' | 'red'> = {
  scheduled: 'green',
  live:      'blue',
  completed: 'purple',
  postponed: 'yellow',
  cancelled: 'gray',
  abandoned: 'red',
}

// ── Component ───────────────────────────────────────────────────────────────

interface MatchCardProps {
  match: MatchResponse
}

export function MatchCard({ match }: MatchCardProps) {
  const navigate = useNavigate()

  const isCompleted = match.status === 'completed'
  const hasScore =
    isCompleted &&
    match.result_home_score !== null &&
    match.result_away_score !== null

  return (
    <Card>
      {/* Top row: teams + status badge */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-white">
            {match.home_team}{' '}
            <span className="font-normal text-gray-500">vs</span>{' '}
            {match.away_team}
          </p>
          <p className="mt-0.5 text-xs text-gray-400">{match.competition}</p>
        </div>
        <Badge variant={STATUS_VARIANTS[match.status]}>
          {STATUS_LABELS[match.status]}
        </Badge>
      </div>

      {/* Bottom row: kickoff info + CTA */}
      <div className="mt-3 flex items-center justify-between gap-2">
        <p className="text-xs text-gray-500">
          {hasScore
            ? `Result: ${match.result_home_score} – ${match.result_away_score}`
            : isCompleted
              ? 'Result pending confirmation'
              : `Kicks off ${formatRelative(match.kickoff_at)} · ${formatDate(match.kickoff_at)}`}
        </p>

        {match.is_betting_open ? (
          <Button
            size="sm"
            onClick={() => navigate(`/bets/new?matchId=${match.id}`)}
          >
            Create Bet
          </Button>
        ) : (
          /* Only show "Betting closed" label for scheduled matches past cutoff.
             Completed/cancelled/etc. have their own status badge above. */
          match.status === 'scheduled' && (
            <span className="text-xs text-gray-500">Betting closed</span>
          )
        )}
      </div>
    </Card>
  )
}
