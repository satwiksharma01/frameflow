import { Check, LoaderCircle, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Described } from '@shared/types'
import { startBuild, useBuild, type Build } from './builds'
import { summary } from './model'

/** What the last build found, or what a build is doing now, in one line. */
export function BuildLine({
  build,
  described
}: {
  build: Build
  described: Described
}): React.JSX.Element {
  return (
    <p className="min-w-0 flex-1 truncate text-[12px] text-quiet" aria-live="polite">
      {build.state === 'building'
        ? build.detail
        : build.state === 'failed'
          ? 'The build did not finish.'
          : build.state === 'previewing'
            ? `${summary(described)} Making the preview…`
            : summary(described)}
    </p>
  )
}

/** A job's steps as the engine says them: done ones ticked, the last one turning while the job runs, or
 *  crossed where it stopped. */
export function Steps({
  label,
  steps,
  running,
  failed
}: {
  label: string
  steps: string[]
  running: boolean
  failed: boolean
}): React.JSX.Element | null {
  if (steps.length === 0) return null
  return (
    <ol aria-label={label} className="flex min-w-0 items-center gap-4 text-[12px]">
      {steps.map((step, i) => {
        const last = i === steps.length - 1
        const state = last && running ? 'current' : last && failed ? 'failed' : 'done'
        const Icon = state === 'current' ? LoaderCircle : state === 'failed' ? X : Check
        return (
          <li
            key={i}
            data-state={state}
            className={cn(
              'flex items-center gap-1.5 whitespace-nowrap',
              state === 'current'
                ? 'text-ink'
                : state === 'failed'
                  ? 'text-signal-ink'
                  : 'text-quiet'
            )}
          >
            <Icon aria-hidden className={cn('size-3.5', state === 'current' && 'animate-spin')} />
            {step}
          </li>
        )
      })}
    </ol>
  )
}

interface Props {
  folder: string
  described: Described
  /** Called when a build of this video has ended well, so the storyboard can be read again. */
  onBuilt: () => void
}

/** The storyboard's footer: what the last build found, and Build. While it builds, the engine's steps
 *  appear beside the button as they happen; if it fails, what the engine said stays above the bar and
 *  the step it stopped on is marked. Once built, its preview is made while Build is offered again. */
export function BuildBar({ folder, described, onBuilt }: Props): React.JSX.Element {
  const build = useBuild(folder)
  const seen = useRef(build.built)
  useEffect(() => {
    if (build.built > seen.current) onBuilt()
    seen.current = build.built
  }, [build.built, onBuilt])

  const building = build.state === 'building'
  const failed = build.state === 'failed'
  return (
    <>
      {failed && (
        <div
          role="alert"
          className="absolute inset-x-6 bottom-full mb-3 max-h-48 select-text overflow-y-auto whitespace-pre-wrap rounded-xl border bg-ground px-4 py-3 text-[13px] text-signal-ink"
        >
          {build.message}
        </div>
      )}
      <BuildLine build={build} described={described} />
      <Steps label="Build steps" steps={build.steps} running={building} failed={failed} />
      <Button
        onClick={() => startBuild(folder)}
        disabled={building}
        className="h-10 flex-none rounded-lg px-[22px] text-[13px] font-bold"
      >
        {building ? 'Building' : failed ? 'Build again' : 'Build video'}
      </Button>
    </>
  )
}
