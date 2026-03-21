import type { BetStatus } from '../../api/types'

type BadgeVariant = 'green' | 'blue' | 'yellow' | 'red' | 'gray' | 'purple'

const variantClasses: Record<BadgeVariant, string> = {
  green:  'bg-green-900/60 text-green-300 border-green-700/50',
  blue:   'bg-blue-900/60 text-blue-300 border-blue-700/50',
  yellow: 'bg-yellow-900/60 text-yellow-300 border-yellow-700/50',
  red:    'bg-red-900/60 text-red-300 border-red-700/50',
  gray:   'bg-gray-800 text-gray-400 border-gray-700',
  purple: 'bg-purple-900/60 text-purple-300 border-purple-700/50',
}

interface BadgeProps {
  variant?: BadgeVariant
  children: React.ReactNode
}

export function Badge({ variant = 'gray', children }: BadgeProps) {
  return (
    <span
      className={[
        'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium',
        variantClasses[variant],
      ].join(' ')}
    >
      {children}
    </span>
  )
}

export const betStatusVariant: Record<BetStatus, BadgeVariant> = {
  OPEN:               'green',
  MATCHED:            'blue',
  PENDING_SETTLEMENT: 'yellow',
  SETTLED:            'purple',
  CANCELLED:          'gray',
  VOIDED:             'red',
  UNDER_REVIEW:       'yellow',
}
