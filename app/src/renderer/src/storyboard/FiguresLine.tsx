import { cn } from '@/lib/utils'
import { clock, type Figures } from './model'

/** The two figures a storyboard opens with: how many scenes, and how long it runs against what was
 *  asked for. The running time turns red only when it is well over. */
export function FiguresLine({ figures }: { figures: Figures }): React.JSX.Element {
  const long = figures.target >= 60
  const say = (seconds: number): string =>
    long ? clock(seconds) : String(Math.round(seconds * 10) / 10)
  return (
    <div
      role="group"
      aria-label="Length"
      className="flex items-baseline gap-7 text-[40px] font-bold leading-none tracking-[-0.03em] tabular-nums"
    >
      <div>
        {figures.scenes}
        <small className="ml-1.5 text-[14px] font-medium tracking-normal text-quiet">
          {' '}
          {figures.scenes === 1 ? 'scene' : 'scenes'}
        </small>
      </div>
      <div>
        {figures.estimated && figures.seconds !== null && (
          <small className="mr-1.5 text-[14px] font-medium tracking-normal text-quiet">
            about{' '}
          </small>
        )}
        <span className={cn(figures.over && 'text-signal-ink')}>
          {figures.seconds === null ? '–' : say(figures.seconds)}
        </span>
        {figures.target > 0 && <span className="text-faint">/{say(figures.target)}</span>}
        <small className="ml-1.5 text-[14px] font-medium tracking-normal text-quiet">
          {' '}
          {long ? 'minutes' : 'seconds'}
        </small>
      </div>
    </div>
  )
}
