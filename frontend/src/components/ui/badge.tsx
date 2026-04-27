import { type VariantProps, cva } from 'class-variance-authority'
import * as React from 'react'

import { cn } from '@/lib/utils'

const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-md border px-2 py-0.5 text-xs font-medium w-fit whitespace-nowrap shrink-0 [&>svg]:size-3 gap-1 [&>svg]:pointer-events-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive transition-colors",
  {
    variants: {
      variant: {
        default:
          'border-transparent bg-primary text-primary-foreground shadow-xs',
        secondary:
          'border-transparent bg-secondary text-secondary-foreground',
        destructive:
          'border-transparent bg-destructive text-white shadow-xs',
        outline: 'text-foreground',
        // Status-specific variants
        pending:
          'border-transparent bg-secondary text-secondary-foreground',
        in_progress:
          'border-transparent bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300',
        complete:
          'border-transparent bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
        errored:
          'border-transparent bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

export interface BadgeProps
  extends React.ComponentProps<'span'>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span
      data-slot="badge"
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

/**
 * Maps a status string to the matching badge variant.
 * Falls back to 'secondary' for unknown statuses.
 */
export function statusToBadgeVariant(
  status: string,
): NonNullable<VariantProps<typeof badgeVariants>['variant']> {
  switch (status) {
    case 'pending':
      return 'pending'
    case 'in_progress':
      return 'in_progress'
    case 'complete':
      return 'complete'
    case 'errored':
      return 'errored'
    default:
      return 'secondary'
  }
}

export { Badge, badgeVariants }
