import { api } from './client'
import type { PaginatedResponse, TransactionResponse, WalletResponse } from './types'

export const walletApi = {
  get: () => api.get<WalletResponse>('/wallet'),

  transactions: (page = 1, pageSize = 20) =>
    api.get<PaginatedResponse<TransactionResponse>>(
      `/wallet/transactions?page=${page}&page_size=${pageSize}`,
    ),
}
