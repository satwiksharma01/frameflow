import { useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { SettingsView } from '@shared/types'
import { stopThinking, think, thinker, useThought } from '../prompt/thinking'
import { say } from '../shell/say'
import type { StoryboardState } from '../storyboard/useStoryboard'

const FIELD = 'Change it in words, like “make scene 4 shorter”'

// The storyboard each video's field is shown with: a change that lands after the creator has gone to the
// other step is read again, and undone, on the one they are on.
const shown = new Map<string, StoryboardState>()

export interface ChangeInWordsHandle {
  /** Put the cursor in the field, once the palette that asked has closed. */
  focus(): void
}

interface Props {
  folder: string
  state: StoryboardState
  /** Called once Enter has sent the words or Esc has let them go, to give the focus back. */
  onDone?(): void
  /** Opens the settings page, where a thinker's problem is fixed. */
  onSettings?(): void
  ref?: Ref<ChangeInWordsHandle>
}

/** The footer's field for a change to the whole storyboard in the creator's words, made by the thinker as
 *  one change with one Undo. The sentence stays in it while the thinker works; nothing changes until the
 *  change lands. */
export function ChangeInWords({
  folder,
  state,
  onDone,
  onSettings,
  ref
}: Props): React.JSX.Element {
  const thought = useThought(folder)
  const [words, setWords] = useState('')
  const [view, setView] = useState<SettingsView | null>(null)
  const field = useRef<HTMLInputElement>(null)
  useImperativeHandle(ref, () => ({
    focus: () => requestAnimationFrame(() => field.current?.focus())
  }))

  useEffect(() => {
    shown.set(folder, state)
    return () => {
      if (shown.get(folder) === state) shown.delete(folder)
    }
  })
  useEffect(() => {
    // Asked inside a promise, so an engine with no `settings` at all (a test's) fails as an unread one
    // does, rather than throwing here: without them, it names no thinker.
    Promise.resolve()
      .then(() => window.frameflow.settings())
      .then(setView, () => {})
  }, [])
  // Ctrl L goes to the field from anywhere on the step, a field included.
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'l') return
      event.preventDefault()
      field.current?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Any job for the video holds the field: a change sent now would stop it, an Approve half written.
  const busy = thought.running
  // The change being made, kept with the job: leaving the step and coming back finds it still here.
  const asked = busy && thought.request?.kind === 'change' ? thought.request.words : null
  const name = thinker(view).name
  const step = thought.steps.at(-1)

  const send = (): void => {
    const request = {
      kind: 'change' as const,
      words: words.trim(),
      version: state.described?.version ?? ''
    }
    const title = state.described?.title
    onDone?.()
    void think(folder, request).then((done) => {
      if (!done || done.stopped) return // replaced by a newer job, which says what it does, or stopped
      const screen = shown.get(folder)
      // A sentence that failed, or met a storyboard changed meanwhile, stays to be sent again.
      if (done.ok || done.refused) setWords('')
      if (done.ok) {
        const { summary, notes } = done.result as { summary: string; notes: string[] }
        if (!screen) {
          // Its video is no longer on screen: named, and apart from the shown video's toast and Undo.
          toast(summary, { id: 'words', description: title })
          return
        }
        screen.reload()
        say(summary, {
          description: notes.join(' ') || undefined,
          undo: () => void shown.get(folder)?.undo()
        })
      } else if (done.changed) {
        say(done.message ?? '')
        screen?.reload()
      } else if (done.refused) {
        say('That can’t be changed in words yet.', {
          description: 'Change it by hand on the storyboard, or in OpenShot.'
        })
      } else if (onSettings && done.message?.includes('Settings')) {
        // The engine's agent and key problems all say where to fix them.
        toast(done.message, { id: 'edit', action: { label: 'Open Settings', onClick: onSettings } })
      } else say(done.message ?? '')
    })
  }

  return (
    // A label, so a click on its edge or its hint puts the cursor in the field.
    <label className="flex h-10 w-[460px] min-w-0 cursor-text items-center gap-2.5 rounded-lg border border-dim px-3.5 focus-within:border-ink focus-within:ring-[3px] focus-within:ring-ink/50">
      <Input
        ref={field}
        aria-label={FIELD}
        aria-keyshortcuts="Control+L"
        placeholder={FIELD}
        value={asked ?? words}
        readOnly={busy}
        onChange={(e) => setWords(e.target.value)}
        onKeyDown={(e) => {
          if (busy) return // its keys wait until the job has ended
          if (e.key === 'Enter' && !e.nativeEvent.isComposing && words.trim()) {
            e.preventDefault()
            send()
          } else if (e.key === 'Escape') {
            e.preventDefault()
            e.currentTarget.blur()
            onDone?.()
          }
        }}
        className="h-full flex-1 rounded-none border-0 px-0 text-[13px] text-ink shadow-none placeholder:text-quiet focus-visible:ring-0 md:text-[13px] dark:bg-transparent"
      />
      {/* A plan's job says its step in the engine's words, as the prompt step's footer does. */}
      <span aria-live="polite" className="truncate text-[12px] text-quiet">
        {!busy ? (
          <span aria-hidden>Ctrl L</span>
        ) : asked === null ? (
          step && `${step}…`
        ) : name ? (
          `Making the change with ${name}…`
        ) : (
          'Making the change…'
        )}
      </span>
      {asked !== null && (
        // The sentence stays in the field, with the cursor, to change and send again.
        <Button
          type="button"
          variant="ghost"
          size="xs"
          aria-label="Stop the change"
          onClick={() => {
            field.current?.focus()
            stopThinking(folder)
          }}
          className="-mr-1.5 flex-none text-[12px] font-bold text-ink"
        >
          Stop
        </Button>
      )}
    </label>
  )
}
