import { cn } from '@/lib/utils'
import { Suggested } from './ChapterHeading'
import { clock, type SectionView } from './model'

interface Props {
  sections: SectionView[]
  current: number
  onJump: (section: SectionView) => void
}

/** The video's chapters down the side: where you are, and a way to jump through a long storyboard. */
export function SectionIndex({ sections, current, onJump }: Props): React.JSX.Element {
  return (
    <nav aria-label="Chapters" className="w-44 flex-none overflow-y-auto border-r px-4 py-6">
      {sections.map((section) => (
        <button
          key={section.number}
          type="button"
          aria-current={section.number === current ? 'true' : undefined}
          onClick={() => onJump(section)}
          className={cn(
            'grid min-h-11 w-full cursor-pointer grid-cols-[24px_1fr] content-center border-t py-2 text-left text-[13px]',
            'transition-colors duration-150 hover:text-ink',
            section.number === current ? 'border-t-2 border-ink text-ink' : 'text-quiet'
          )}
        >
          <b className="font-bold">{String(section.number).padStart(2, '0')}</b>
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="truncate">{section.title}</span>
            {!section.confirmed && <Suggested />}
          </span>
          <span className="time col-start-2 text-[12px] text-quiet">
            {section.start !== null && `${clock(section.start)} · `}
            {section.scenes.length} {section.scenes.length === 1 ? 'scene' : 'scenes'}
          </span>
        </button>
      ))}
    </nav>
  )
}
