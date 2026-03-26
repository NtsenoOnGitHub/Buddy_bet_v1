import { api } from './client'
import type { MatchResponse, MatchStatus, PaginatedResponse } from './types'

export interface MatchListParams {
  page?: number
  pageSize?: number
  /** Filter by match status. Omit for all statuses. */
  status?: MatchStatus
  /** Case-insensitive substring filter on competition name. */
  competition?: string
}

export const matchesApi = {
  list: ({ page = 1, pageSize = 20, status, competition }: MatchListParams = {}) => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    })
    if (status) params.set('status', status)
    if (competition) params.set('competition', competition)
    return api.get<PaginatedResponse<MatchResponse>>(`/matches?${params}`)
  },

  get: (matchId: string) => api.get<MatchResponse>(`/matches/${matchId}`),
}
