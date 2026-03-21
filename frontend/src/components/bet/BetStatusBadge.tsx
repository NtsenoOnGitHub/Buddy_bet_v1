import { Badge, betStatusVariant } from '../ui/Badge'
import type { BetStatus } from '../../api/types'

const labels: Record<BetStatus, string> = {
  OPEN:               'Open',
  MATCHED:            'Matched',
  PENDING_SETTLEMENT: 'Settling',
  SETTLED:            'Settled',
  CANCELLED:          'Cancelled',
  VOIDED:             'Voided',
  UNDER_REVIEW:       'Under Review',
}

export function BetStatusBadge({ status }: { status: BetStatus }) {
  return (
    <Badge variant={betStatusVariant[status]}>
      {labels[status]}
    </Badge>
  )
}
