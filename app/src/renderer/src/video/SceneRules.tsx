import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { numbered, type SceneView } from '../storyboard/model'

interface Props {
  scenes: SceneView[]
  /** The scene the player is at, or null while there is nothing to play. */
  current: SceneView | null
  /** How far through the current scene the player is, 0 to 1. */
  at: number
  onJump(scene: SceneView): void
}

/** Every scene's rule end to end under the player, each as wide as the scene is long: the way through the
 *  video. Played ones are ink, the current one red with the playhead, those ahead dim grey; the
 *  first, current, next and last numbers sit under them where they fit. A click jumps to a scene. */
export function SceneRules({ scenes, current, at, onJump }: Props): React.JSX.Element {
  // The strip is as wide as the frame, which the window's size sets.
  const strip = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(strip.current!)
    return () => observer.disconnect()
  }, [])
  const shown = numbered(scenes, current, width)
  return (
    <div ref={strip} role="group" aria-label="Scenes" className="mt-3.5 flex gap-0.5">
      {scenes.map((scene) => {
        const state = !current
          ? 'ahead'
          : scene.number < current.number
            ? 'played'
            : scene.number === current.number
              ? 'current'
              : 'ahead'
        return (
          <button
            key={scene.key}
            type="button"
            tabIndex={-1} // the arrows go from scene to scene
            disabled={!current}
            aria-label={`Scene ${scene.number}`}
            aria-current={state === 'current' || undefined}
            data-rule={state}
            onClick={() => onJump(scene)}
            style={{ flexGrow: scene.seconds ?? 0 }}
            className="h-8 min-w-0 basis-0 pt-[4.5px] text-left"
          >
            <span
              data-bar
              className={cn(
                'relative block h-[3px] rounded-[2px]',
                state === 'played' ? 'bg-ink' : state === 'current' ? 'bg-signal' : 'bg-dim'
              )}
            >
              {state === 'current' && (
                <span
                  aria-hidden
                  className="absolute -top-[4.5px] h-3 w-px bg-ink"
                  style={{ left: `${at * 100}%` }}
                />
              )}
            </span>
            <span
              aria-hidden
              className={cn(
                'mt-2 block whitespace-nowrap text-[12px] leading-[14px] text-quiet',
                state === 'current' && 'font-bold text-ink'
              )}
            >
              {shown.includes(scene.number) && String(scene.number).padStart(2, '0')}
            </span>
          </button>
        )
      })}
    </div>
  )
}
