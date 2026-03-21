import { useNavigate } from 'react-router-dom'
import { Card } from '../ui/Card'
import { BetStatusBadge } from './BetStatusBadge'
import { Button } from '../ui/Button'
import { formatMoney } from '../../utils/money'
import { formatRelative } from '../../utils/date'
import type { BetResponse } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'

const outcomeLabel: Record<string, string> = {
  home_win: 'Home Win',
  away_win: 'Away Win',
  draw:     'Draw',
}

interface BetCardProps {
  bet: BetResponse
  /** Show an Accept button (used on the open-bets feed). */
  showAccept?: boolean
}

export function BetCard({ bet, showAccept = false }: BetCardProps) {
  const navigate = useNavigate()
  const { user } = useAuth()
  const isOwn = user?.id === bet.creator_id

  return (
    <Card
      className="cursor-pointer transition-colors hover:border-gray-700"
      onClick={() => navigate(`/bets/${bet.id}`)}
    >
      {/* Match header */}
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">
            {bet.match.home_team} vs {bet.match.away_team}
          </p>
          <p className="text-xs text-gray-500">
            {bet.match.competition} · kicks off {formatRelative(bet.match.kickoff_at)}
          </p>
        </div>
        <BetStatusBadge status={bet.status} />
      </div>

      {/* Stake + predictions */}
      <div className="flex items-center gap-4 text-sm">
        <div>
          <p className="text-xs text-gray-500">Stake</p>
          <p className="font-semibold text-brand-400">
            {formatMoney(bet.stake_amount, bet.currency)}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Pick</p>
          <p className="font-medium text-gray-200">
            {outcomeLabel[bet.creator_prediction] ?? bet.creator_prediction}
          </p>
        </div>
        {bet.settlement_outcome && (
          <div>
            <p className="text-xs text-gray-500">Outcome</p>
            <p className="font-medium text-gray-200 capitalize">
              {bet.settlement_outcome.replace('_', ' ')}
            </p>
          </div>
        )}
        {bet.payout_amount && (
          <div>
            <p className="text-xs text-gray-500">Payout</p>
            <p className="font-semibold text-brand-400">
              {formatMoney(bet.payout_amount, bet.currency)}
            </p>
          </div>
        )}
      </div>

      {/* Accept button — stop propagation so click doesn't also navigate */}
      {showAccept && !isOwn && bet.status === 'OPEN' && (
        <div className="mt-3 flex justify-end">
          <Button
            size="sm"
            onClick={(e) => {
              e.stopPropagation()
              navigate(`/bets/${bet.id}`)
            }}
          >
            Accept Bet
          </Button>
        </div>
      )}
    </Card>
  )
}
