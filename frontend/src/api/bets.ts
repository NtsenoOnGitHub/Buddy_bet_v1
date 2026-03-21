import { api } from './client'
import type { BetResponse, BetStatus, FootballOutcome, PaginatedResponse } from './types'

export interface CreateBetPayload {
  match_id: string
  creator_prediction: FootballOutcome
  stake_amount: string   // decimal string
}

export interface AcceptBetPayload {
  opponent_prediction: FootballOutcome
}

export const betsApi = {
  listOpen: (page = 1, pageSize = 20) =>
    api.get<PaginatedResponse<BetResponse>>(
      `/bets/open?page=${page}&page_size=${pageSize}`,
    ),

  listMy: (page = 1, pageSize = 20, status?: BetStatus) => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    })
    if (status) params.set('status', status)
    return api.get<PaginatedResponse<BetResponse>>(`/bets/my?${params}`)
  },

  get: (betId: string) => api.get<BetResponse>(`/bets/${betId}`),

  create: (payload: CreateBetPayload) =>
    api.post<BetResponse>('/bets', payload),

  accept: (betId: string, payload: AcceptBetPayload) =>
    api.post<BetResponse>(`/bets/${betId}/accept`, payload),

  cancel: (betId: string) =>
    api.post<BetResponse>(`/bets/${betId}/cancel`),
}
