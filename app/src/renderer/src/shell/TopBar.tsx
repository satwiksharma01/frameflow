import { cn } from '@/lib/utils'

export type Step = 'prompt' | 'storyboard' | 'video'

const STEPS: { name: string; step: Step }[] = [
  { name: 'Prompt', step: 'prompt' },
  { name: 'Storyboard', step: 'storyboard' },
  { name: 'Video', step: 'video' }
]

/** The video's name and its three steps, the current one marked. Until a plan is approved and its
 *  storyboard written, only the prompt is open. */
export function TopBar({
  title,
  step,
  ready,
  onStep
}: {
  title: string
  step: Step
  /** Whether the video has a storyboard. */
  ready: boolean
  onStep(step: Step): void
}): React.JSX.Element {
  return (
    <header className="flex h-[52px] flex-none items-center gap-2 border-b px-6 text-[13px]">
      <h1 className="mr-auto truncate text-[14px] font-bold">{title}</h1>
      <ol aria-label="Steps" className="flex items-center gap-1">
        {STEPS.map(({ name, step: to }) => {
          const current = to === step
          const open = ready || to === 'prompt'
          return (
            <li key={name}>
              <button
                type="button"
                disabled={!open}
                aria-current={current ? 'step' : undefined}
                onClick={() => {
                  if (!current) onStep(to)
                }}
                className={cn(
                  'h-8 rounded-md px-3 transition-colors duration-150',
                  current
                    ? 'font-medium text-ink'
                    : open
                      ? 'text-quiet hover:text-ink'
                      : 'text-faint'
                )}
              >
                {name}
              </button>
            </li>
          )
        })}
      </ol>
    </header>
  )
}
