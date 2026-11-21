import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useId } from 'react'
import { reducedMotion, SPRING_MS, springEasing } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { Described } from '@shared/types'
import { clock, type SceneView } from './model'
import { Thumbnail } from './Thumbnail'

interface Props {
  scene: SceneView
  folder: string
  aspect: Described['aspect']
  selected: boolean
  onSelect: () => void
}

const EASING = springEasing()

/** One scene on the storyboard: a rule as long as the scene lasts, its number and time, its picture
 *  and what is said. The rule is red on the selected scene only. */
export function SceneModule({
  scene,
  folder,
  aspect,
  selected,
  onSelect
}: Props): React.JSX.Element {
  const wide = aspect === '16:9'
  // Dragged, it follows the pointer from where it was grabbed; the others move aside on the spring. Only the
  // selected scene is a tab stop, so dnd-kit's own is left off.
  const { setNodeRef, listeners, attributes, transform, transition, isDragging } = useSortable({
    id: scene.key,
    transition: reducedMotion() ? null : { duration: SPRING_MS, easing: EASING }
  })
  // The label replaces what the card shows, so its length and checks are read after it, then how to move it.
  const about = useId()
  const heard = [
    scene.seconds !== null && `${scene.seconds.toFixed(1)} seconds.`,
    ...scene.checks.map((check) => `Check: ${check.what}.`)
  ].filter(Boolean)
  return (
    <div
      ref={setNodeRef}
      role="button"
      aria-current={selected || undefined}
      aria-label={`Scene ${scene.number}: ${scene.says || scene.source}`}
      aria-roledescription={attributes['aria-roledescription']}
      aria-describedby={
        heard.length ? `${about} ${attributes['aria-describedby']}` : attributes['aria-describedby']
      }
      tabIndex={selected ? 0 : -1}
      data-scene={scene.number}
      data-dragging={isDragging || undefined}
      onClick={onSelect}
      {...listeners}
      style={{
        transform: CSS.Translate.toString(transform),
        transition: [transition, 'scale 100ms ease-out'].filter(Boolean).join(', ')
      }}
      className={cn(
        'group relative cursor-default touch-none rounded-sm pt-2.5 outline-offset-4 active:scale-[0.98]',
        isDragging && 'z-10 scale-[1.02] outline outline-1 outline-ink active:scale-[1.02]'
      )}
    >
      {heard.length > 0 && (
        <span id={about} hidden>
          {heard.join(' ')}
        </span>
      )}
      <span aria-hidden className="absolute inset-x-0 top-px h-px bg-line" />
      {scene.seconds === null ? (
        // No length yet, so no rule to draw: the hairline alone carries the selection.
        selected && <span aria-hidden className="absolute inset-x-0 top-px h-px bg-signal" />
      ) : (
        <span
          aria-hidden
          data-rule={selected ? 'selected' : 'plain'}
          style={{ width: `${scene.rule * 100}%` }}
          className={cn(
            'absolute left-0 top-0 h-[3px] min-w-1 rounded-[2px] transition-colors duration-150',
            selected ? 'bg-signal' : 'bg-ink'
          )}
        />
      )}
      <div className="flex items-baseline gap-2.5 text-[12px] text-quiet">
        <b className="text-[15px] font-bold text-ink">{String(scene.number).padStart(2, '0')}</b>
        {scene.start !== null && <span className="time">{clock(scene.start)}</span>}
        {scene.seconds !== null && (
          <span className="time ml-auto">{scene.seconds.toFixed(1)} s</span>
        )}
      </div>
      <div className={cn('mt-2 flex gap-3', wide && 'flex-col gap-2.5')}>
        <Thumbnail
          folder={folder}
          number={scene.number}
          pictureKey={scene.key}
          aspect={aspect}
          title={scene.text}
          className={cn(
            'rounded-md',
            wide ? 'w-full text-[22px]' : aspect === '1:1' ? 'w-[120px]' : 'w-[88px]'
          )}
        />
        <div className="min-w-0">
          <p className="line-clamp-6 text-[15px] leading-[1.32] first-letter:uppercase">
            {scene.says}
          </p>
          {scene.checks.map((check, i) => (
            <p key={i} className="mt-2.5 text-[12px] text-signal-ink">
              {check.what}
            </p>
          ))}
        </div>
      </div>
    </div>
  )
}
