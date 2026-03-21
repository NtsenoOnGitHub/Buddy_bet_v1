import { api } from './client'
import type {
  FootballOutcome,
  PendingSettlementListResponse,
  SettlementSummaryResponse,
  ManualSettleBetResponse,
  VoidBetResponse,
} from './types'

export interface ConfirmResultPayload {
  outcome: FootballOutcome
  home_score: number
  away_score: number
}

export const adminApi = {
  listPending(matchId?: string): Promise<PendingSettlementListResponse> {
    const qs = matchId ? `?match_id=${matchId}` : ''
    return api.get(`/admin/bets/pending${qs}`)
  },

  confirmResult(
    matchId: string,
    payload: ConfirmResultPayload,
  ): Promise<SettlementSummaryResponse> {
    return api.post(`/admin/matches/${matchId}/confirm-result`, payload)
  },

  settleBet(betId: string): Promise<ManualSettleBetResponse> {
    return api.post(`/admin/bets/${betId}/settle`)
  },

  voidBet(betId: string, reason: string): Promise<VoidBetResponse> {
    return api.post(`/admin/bets/${betId}/void`, { reason })
  },
}
