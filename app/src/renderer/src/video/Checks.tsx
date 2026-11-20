import { Headphones } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** How many checks the last build found on the scenes: red while there is one. */
export function CheckCount({ count }: { count: number }): React.JSX.Element {
  return (
    <span
      className={cn('ml-auto text-[14px] font-medium', count ? 'text-signal-ink' : 'text-quiet')}
    >
      {count ? `${count} to check` : 'Nothing to check'}
    </span>
  )
}

interface Props {
  /** What the build found, worded as found. */
  check: string
  /** Off while there is no picture to play. */
  canListen: boolean
  onListen(): void
  onGoTo(): void
}

/** A scene's check under its words: what was found, Listen around its moment, and the way to the scene on
 *  the storyboard. */
export function Check({ check, canListen, onListen, onGoTo }: Props): React.JSX.Element {
  return (
    <div className="col-[4/6] mt-2 flex items-center gap-3.5 text-[12px] text-signal-ink">
      {check}
      <Button
        type="button"
        variant="ghost"
        disabled={!canListen}
        onClick={onListen}
        className="h-8 rounded-md border border-ink px-3 text-[12px] text-ink disabled:border-dim disabled:text-faint disabled:opacity-100"
      >
        <Headphones aria-hidden className="size-3.5" />
        Listen
      </Button>
      <Button
        type="button"
        variant="ghost"
        onClick={onGoTo}
        className="h-8 px-1 text-[12px] font-normal text-quiet hover:bg-transparent hover:text-ink"
      >
        Open in the storyboard
      </Button>
    </div>
  )
}
