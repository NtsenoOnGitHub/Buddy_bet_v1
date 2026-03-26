// ── Enums ───────────────────────────────────────────────────────────────────

export type BetStatus =
  | 'OPEN'
  | 'MATCHED'
  | 'PENDING_SETTLEMENT'
  | 'SETTLED'
  | 'CANCELLED'
  | 'VOIDED'
  | 'UNDER_REVIEW'

export type FootballOutcome = 'home_win' | 'away_win' | 'draw'

export type SettlementOutcome =
  | 'creator_wins'
  | 'opponent_wins'
  | 'no_winner'
  | 'voided'

export type MatchStatus =
  | 'scheduled'
  | 'live'
  | 'completed'
  | 'postponed'
  | 'cancelled'
  | 'abandoned'

export type UserRole = 'user' | 'admin'
export type UserStatus = 'active' | 'suspended' | 'banned' | 'under_review'

export type LedgerEntryType =
  | 'STAKE_LOCK'
  | 'STAKE_UNLOCK'
  | 'VOID_REFUND'
  | 'SETTLEMENT_DEDUCT'
  | 'FEE_DEDUCT'
  | 'PAYOUT_CREDIT'
  | 'REFUND_CREDIT'

export type BalanceField = 'available' | 'locked'
export type LedgerDirection = 'credit' | 'debit'

// ── DTOs ────────────────────────────────────────────────────────────────────

export interface UserResponse {
  id: string
  email: string
  display_name: string
  phone_number: string | null
  role: UserRole
  status: UserStatus
  created_at: string
  updated_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: UserResponse
}

export interface MatchResponse {
  id: string
  external_id: string
  home_team: string
  away_team: string
  competition: string
  kickoff_at: string
  status: MatchStatus
  result_home_score: number | null
  result_away_score: number | null
  outcome: FootballOutcome | null
  result_confirmed_at: string | null
  created_at: string
  updated_at: string
  /** Computed by the backend: true when status=scheduled AND kickoff cutoff has not passed. */
  is_betting_open: boolean
}

export interface BetResponse {
  id: string
  match_id: string
  creator_id: string
  opponent_id: string | null
  creator_prediction: FootballOutcome
  opponent_prediction: FootballOutcome | null
  stake_amount: string              // decimal string
  currency: string
  status: BetStatus
  settlement_outcome: SettlementOutcome | null
  winner_id: string | null
  platform_fee: string | null       // decimal string
  payout_amount: string | null      // decimal string
  applied_winner_fee_rate: string | null
  applied_no_winner_fee_rate: string | null
  expires_at: string
  settled_at: string | null
  created_at: string
  updated_at: string
  match: MatchResponse
}

export interface WalletResponse {
  id: string
  user_id: string
  available_balance: string   // decimal string
  locked_balance: string      // decimal string
  total_balance: string       // decimal string — computed: available + locked
  currency: string
  version: number
  updated_at: string
}

export interface TransactionResponse {
  id: string
  user_id: string
  wallet_id: string
  entry_type: LedgerEntryType
  balance_field: BalanceField
  direction: LedgerDirection
  amount: string                      // decimal string
  reference_type: string
  reference_id: string
  available_balance_after: string     // decimal string
  locked_balance_after: string        // decimal string
  notes: string | null
  created_at: string
}

// ── Pagination ───────────────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

// ── Admin ─────────────────────────────────────────────────────────────────────

export interface PendingSettlementItem {
  id: string
  match_id: string
  creator_id: string
  opponent_id: string | null
  stake_amount: string
  currency: string
  updated_at: string | null
}

export interface PendingSettlementListResponse {
  items: PendingSettlementItem[]
  total: number
}

export interface SettlementSummaryResponse {
  match_id: string
  outcome: string
  bets_found: number
  bets_settled: number
  bets_already_settled: number
  bets_failed: number
  failed_bet_ids: string[]
  failure_reasons: Record<string, string>
}

export interface ManualSettleBetResponse {
  bet_id: string
  message: string
  settlement_outcome: string | null
  winner_id: string | null
  payout_amount: string | null
  platform_fee: string | null
}

export interface VoidBetResponse {
  bet_id: string
  refunded_user_ids: string[]
  message: string
}

// ── Errors ───────────────────────────────────────────────────────────────────

export interface FieldError {
  field: string
  message: string
}

export type ApiErrorDetail = string | FieldError[]
