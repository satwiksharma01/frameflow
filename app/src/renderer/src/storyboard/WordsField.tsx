import { useImperativeHandle, useRef, useState, type Ref } from 'react'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { EditResult } from './useStoryboard'

export interface WordsFieldHandle {
  /** Open the words for typing, as Enter on a scene does. */
  open(): void
}

interface Props {
  label: string
  /** A line under the label, saying what changing the words does. */
  hint?: string
  words: string
  /** What shows while the change is on its way, if anything. */
  looking?: string
  onCommit(words: string): Promise<EditResult>
  /** Called once Enter has sent the words or Esc has let them go, to give the focus back. */
  onDone?(): void
  ref?: Ref<WordsFieldHandle>
}

/** A scene's words: shown as they are, opened with a click or Enter, sent with Enter, left with Esc.
 *  A change that is refused says why under the field, and the words go back. */
export function WordsField({
  label,
  hint,
  words,
  looking,
  onCommit,
  onDone,
  ref
}: Props): React.JSX.Element {
  const [draft, setDraft] = useState<string | null>(null) // null while the words are only shown
  const [waiting, setWaiting] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const field = useRef<HTMLTextAreaElement>(null)
  const cancelled = useRef(false) // Esc: the blur that follows sends nothing

  const open = (): void => {
    cancelled.current = false
    setProblem(null)
    setDraft(words)
    requestAnimationFrame(() => {
      field.current?.focus()
      field.current?.select()
    })
  }
  useImperativeHandle(ref, () => ({ open }))

  const commit = async (): Promise<void> => {
    if (draft === null || waiting || cancelled.current) return
    if (draft.trim() === words.trim()) return setDraft(null)
    setWaiting(true)
    const result = await onCommit(draft.trim())
    setWaiting(false)
    setDraft(null)
    if (!result.ok) setProblem(result.refused)
  }

  return (
    <div className="mt-4 border-b pb-3">
      {draft === null ? (
        <button
          type="button"
          onClick={open}
          className="block w-full cursor-text rounded-md text-left outline-offset-4"
        >
          <span className="block text-[12px] text-quiet">{label}</span>
          <span
            className={cn(
              'mt-1 block select-text text-[19px] font-medium leading-[1.3] first-letter:uppercase',
              !words && 'text-quiet'
            )}
          >
            {words || 'Nothing is said'}
          </span>
        </button>
      ) : (
        <>
          <span className="block text-[12px] text-quiet">{label}</span>
          <Textarea
            ref={field}
            aria-label={label}
            value={draft}
            disabled={waiting}
            onChange={(e) => setDraft(e.target.value.replace(/\n/g, ' '))}
            onBlur={() => void commit()}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                if (!e.shiftKey && !e.nativeEvent.isComposing) {
                  e.currentTarget.blur() // which sends the words
                  onDone?.()
                }
              } else if (e.key === 'Escape') {
                e.preventDefault()
                e.stopPropagation()
                cancelled.current = true
                setDraft(null)
                onDone?.()
              }
            }}
            className="mt-1 min-h-20 resize-none rounded-md text-[17px] leading-[1.3]"
          />
        </>
      )}
      {waiting && looking ? (
        <p className="mt-1.5 text-[12px] text-quiet">{looking}</p>
      ) : (
        hint && <p className="mt-1.5 text-[12px] text-quiet">{hint}</p>
      )}
      {problem && (
        <p role="alert" className="mt-1.5 text-[12px] text-signal-ink">
          {problem}
        </p>
      )}
    </div>
  )
}
