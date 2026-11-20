import { Ellipsis } from 'lucide-react'
import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import type { EditOp } from '@shared/types'
import { clock, type SectionView } from './model'
import type { EditResult } from './useStoryboard'

/** The tag on a chapter the editor suggested, until the creator renames or keeps it. */
export function Suggested(): React.JSX.Element {
  return (
    <span className="rounded-sm bg-plain px-2 py-0.5 text-[11px] font-normal tracking-normal text-quiet">
      Suggested
    </span>
  )
}

interface Props {
  section: SectionView
  edit(op: EditOp, toast?: string): Promise<EditResult>
  /** Called once the name is sent with Enter or let go with Esc, to give the focus back to the scenes. */
  onDone?(): void
}

/** A chapter's heading: its number and name, the name changed in place, and the chapter kept or removed. */
export function ChapterHeading({ section, edit, onDone }: Props): React.JSX.Element {
  const [draft, setDraft] = useState<string | null>(null)
  const field = useRef<HTMLInputElement>(null)
  const settled = useRef(false) // sent or let go: the blur that follows changes nothing
  const focusName = (): void => {
    field.current?.focus()
    field.current?.select()
  }
  const rename = (): void => {
    settled.current = false
    setDraft(section.title ?? '')
    requestAnimationFrame(focusName)
  }
  const commit = (): void => {
    if (settled.current) return
    settled.current = true
    const title = draft?.trim()
    setDraft(null)
    if (title && title !== section.title)
      void edit({ op: 'rename_chapter', number: section.number, title })
  }
  const last = section.scenes.at(-1)

  return (
    <h2 className="mb-3 mt-6 flex items-baseline gap-2.5 text-[20px] font-bold tracking-[-0.015em]">
      <span className="text-[12px] tracking-normal">{String(section.number).padStart(2, '0')}</span>
      {draft === null ? (
        <button
          type="button"
          onClick={rename}
          className="min-h-8 cursor-text rounded-sm text-left outline-offset-4"
        >
          {section.title}
        </button>
      ) : (
        <Input
          ref={field}
          aria-label="Chapter name"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
              commit()
              onDone?.()
            }
            if (e.key === 'Escape') {
              settled.current = true
              setDraft(null)
              onDone?.()
            }
          }}
          className="h-8 w-56 rounded-md text-[17px] font-bold"
        />
      )}
      {!section.confirmed && <Suggested />}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="Chapter options"
            className="self-center rounded-md text-quiet"
          >
            <Ellipsis aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          className="rounded-xl"
          // A closing menu takes the focus back (to itself as it shrinks from under the pointer, then to
          // its button), so after Rename the name is focused once the menu has gone.
          onCloseAutoFocus={(e) => {
            if (draft === null) return
            e.preventDefault()
            focusName()
          }}
        >
          <DropdownMenuItem
            onSelect={() => {
              settled.current = false
              setDraft(section.title ?? '')
            }}
          >
            Rename
          </DropdownMenuItem>
          {!section.confirmed && (
            <DropdownMenuItem
              onSelect={() => void edit({ op: 'keep_chapter', number: section.number })}
            >
              Keep this chapter
            </DropdownMenuItem>
          )}
          <DropdownMenuItem
            onSelect={() =>
              void edit({ op: 'remove_chapter', number: section.number }, 'Chapter removed')
            }
          >
            Remove chapter
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {section.start !== null && last && (
        <span className="time ml-auto text-[12px] font-normal tracking-normal text-quiet">
          {clock(section.start)}–{clock(last.start! + (last.seconds ?? 0))}
        </span>
      )}
    </h2>
  )
}
