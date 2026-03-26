import { api } from './client'
import type { DepositResponse, InitiateDepositResponse, PaginatedResponse } from './types'

export interface InitiateDepositBody {
  amount: string
  email_address?: string
  name_first?: string
  name_last?: string
}

export const depositsApi = {
  /**
   * Initiate a PayFast deposit. Returns a checkout_url to redirect the user.
   * Wallet is NOT credited at this point.
   */
  initiate: (body: InitiateDepositBody) =>
    api.post<InitiateDepositResponse>('/wallet/deposits/initiate', body),

  /** Fetch a single deposit by ID (own deposits only). */
  get: (id: string) =>
    api.get<DepositResponse>(`/wallet/deposits/${id}`),

  /** List the current user's deposits (paginated). */
  list: (page = 1, pageSize = 20) =>
    api.get<PaginatedResponse<DepositResponse>>(
      `/wallet/deposits?page=${page}&page_size=${pageSize}`,
    ),
}
