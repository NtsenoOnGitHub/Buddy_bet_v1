import { api } from './client'
import type { MatchResponse, PaginatedResponse } from './types'

export const matchesApi = {
  list: (page = 1, pageSize = 20) =>
    api.get<PaginatedResponse<MatchResponse>>(
      `/matches?page=${page}&page_size=${pageSize}`,
    ),

  get: (matchId: string) => api.get<MatchResponse>(`/matches/${matchId}`),
}
