import { useRef, useState } from 'react'
import { say } from './Toasts'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut
} from '@/components/ui/command'
import type { Described, EditOp, NewScene } from '@shared/types'
import type { Action } from '../storyboard/keys'
import type { SectionView } from '../storyboard/model'
import { startBuild } from '../storyboard/builds'
import type { EditResult } from '../storyboard/useStoryboard'

const MOD = /Mac/.test(navigator.platform) ? '⌘' : 'Ctrl'
const two = (n: number): string => String(n).padStart(2, '0')
const firstWords = (says: string | null): string => (says ?? '').split(/\s+/).slice(0, 6).join(' ')

interface Props {
  open: boolean
  onOpenChange(open: boolean): void
  folder: string
  described: Described
  sections: SectionView[]
  selected: number
  /** Runs what a key would: the same change, the same toast. */
  act(action: Action): void
  /** Plays around the selected scene's first check, as its Listen button does. */
  listen(): void
  edit(op: EditOp, toast?: string): Promise<EditResult>
  goTo(number: number): void
  goToChapter(section: SectionView): void
  /** Called once a scene is added, with its kind, as the add tile does. */
  onAdded(kind: NewScene['kind']): void
  /** Called as the palette closes, unless what was chosen put the focus somewhere itself. */
  onClosed(): void
  /** Opens the settings page, where the app has one to open. */
  onSettings?(): void
  /** Puts the cursor in the footer's field that changes the storyboard in words. */
  changeInWords(): void
}

/** Every change the storyboard can make, found by typing: the selected scene's, the video's, and a way
 *  to any scene or chapter. Each shows its keys, so the palette teaches the keyboard. */
export function CommandPalette({
  open,
  onOpenChange,
  folder,
  described,
  sections,
  selected,
  act,
  listen,
  edit,
  goTo,
  goToChapter,
  onAdded,
  onClosed,
  onSettings,
  changeInWords
}: Props): React.JSX.Element {
  // "Add from your recording after it…" asks for the words on a second page.
  const [words, setWords] = useState<string | null>(null)
  const [waiting, setWaiting] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const focused = useRef(false) // the command chosen has put the focus where it is wanted

  const close = (): void => {
    onOpenChange(false)
    setWords(null)
    setProblem(null)
  }
  const run = (thing: () => void) => () => {
    close()
    thing()
  }
  const add = async (scene: NewScene): Promise<EditResult> => {
    const result = await edit(
      { op: 'add', after: selected, scene },
      scene.kind === 'title' ? undefined : 'Scene added'
    )
    if (result.ok) onAdded(scene.kind)
    // The recording page shows its own refusal; the palette is closed for the others.
    else if (scene.kind !== 'recording') say(result.refused)
    return result
  }
  const addWords = async (): Promise<void> => {
    if (!words?.trim() || waiting) return
    setWaiting(true)
    setProblem(null)
    const result = await add({ kind: 'recording', words: words.trim() })
    setWaiting(false)
    if (result.ok) close()
    else setProblem(result.refused)
  }
  const captions = described.video?.spoken_captions
  const checks = sections.flatMap((s) => s.scenes).find((s) => s.number === selected)?.checks ?? []

  return (
    <CommandDialog
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
      title="Commands"
      description="Change the storyboard, or go to a scene or chapter"
      showCloseButton={false}
      onCloseAutoFocus={() => {
        if (!focused.current) onClosed()
        focused.current = false
      }}
      className="top-[18%] translate-y-0 rounded-xl border bg-plain sm:max-w-[560px]"
    >
      {words === null ? (
        <>
          <CommandInput placeholder="Type a command or a scene…" />
          <CommandList className="max-h-[380px]">
            <CommandEmpty>Nothing matches.</CommandEmpty>
            <CommandGroup heading={`Scene ${two(selected)}`}>
              <CommandItem
                onSelect={run(() => {
                  focused.current = true
                  act('edit-words')
                })}
              >
                Change its words<CommandShortcut>Enter</CommandShortcut>
              </CommandItem>
              <CommandItem disabled={!described.preview} onSelect={run(() => act('play'))}>
                Play it<CommandShortcut>Space</CommandShortcut>
              </CommandItem>
              {checks.length > 0 && (
                <CommandItem disabled={!described.preview} onSelect={run(listen)}>
                  Listen to its check
                </CommandItem>
              )}
              <CommandItem disabled={selected <= 1} onSelect={run(() => act('move-earlier'))}>
                Move it earlier<CommandShortcut>Alt ←</CommandShortcut>
              </CommandItem>
              <CommandItem
                disabled={selected >= described.scenes.length}
                onSelect={run(() => act('move-later'))}
              >
                Move it later<CommandShortcut>Alt →</CommandShortcut>
              </CommandItem>
              <CommandItem onSelect={run(() => act('delete'))}>
                Delete it<CommandShortcut>Delete</CommandShortcut>
              </CommandItem>
              <CommandItem
                onSelect={run(() => {
                  focused.current = true // the new title's words on screen take it
                  void add({ kind: 'title', text: 'New title' })
                })}
              >
                Add a title after it
              </CommandItem>
              <CommandItem
                onSelect={run(
                  () =>
                    void window.frameflow
                      .chooseFile()
                      .then((path) => (path ? add({ kind: 'file', path }) : null))
                )}
              >
                Add a file after it…
              </CommandItem>
              <CommandItem onSelect={() => setWords('')}>
                Add from your recording after it…
              </CommandItem>
            </CommandGroup>
            <CommandGroup heading="Video">
              <CommandItem
                onSelect={run(() => {
                  focused.current = true
                  changeInWords()
                })}
              >
                Change it in words<CommandShortcut>{MOD} L</CommandShortcut>
              </CommandItem>
              <CommandItem onSelect={run(() => startBuild(folder))}>Build video</CommandItem>
              <CommandItem disabled={!described.can_undo} onSelect={run(() => act('undo'))}>
                Undo<CommandShortcut>{MOD} Z</CommandShortcut>
              </CommandItem>
              <CommandItem disabled={!described.can_redo} onSelect={run(() => act('redo'))}>
                Redo<CommandShortcut>{MOD} Shift Z</CommandShortcut>
              </CommandItem>
              {captions !== undefined && (
                <CommandItem
                  onSelect={run(
                    () =>
                      void edit(
                        { op: 'video', spoken_captions: !captions },
                        `Word-by-word captions ${captions ? 'off' : 'on'}`
                      )
                  )}
                >
                  Turn word-by-word captions {captions ? 'off' : 'on'}
                </CommandItem>
              )}
            </CommandGroup>
            <CommandGroup heading="Go to">
              {onSettings && (
                <CommandItem
                  onSelect={run(() => {
                    focused.current = true // the storyboard is leaving; its scene does not take the focus
                    onSettings()
                  })}
                >
                  Settings
                </CommandItem>
              )}
              {sections
                .filter((s) => s.title !== null)
                .map((s) => (
                  <CommandItem key={`chapter-${s.number}`} onSelect={run(() => goToChapter(s))}>
                    Chapter {two(s.number)} · {s.title}
                  </CommandItem>
                ))}
              {sections
                .flatMap((s) => s.scenes)
                .map((scene) => (
                  <CommandItem key={scene.key} onSelect={run(() => goTo(scene.number))}>
                    Scene {two(scene.number)} · {firstWords(scene.says || scene.text)}
                  </CommandItem>
                ))}
            </CommandGroup>
          </CommandList>
        </>
      ) : (
        <div className="grid gap-1.5 p-4">
          <label htmlFor="palette-words" className="text-[12px] text-quiet">
            Words you say in it, for a scene after scene {two(selected)}
          </label>
          <input
            id="palette-words"
            autoFocus
            value={words}
            disabled={waiting}
            onChange={(e) => setWords(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.nativeEvent.isComposing) void addWords()
            }}
            className="h-10 rounded-md border bg-transparent px-3 text-[15px] outline-none focus-visible:border-ink"
          />
          {waiting && <p className="text-[12px] text-quiet">Finding it in your recording…</p>}
          {problem && (
            <p role="alert" className="text-[12px] text-signal-ink">
              {problem}
            </p>
          )}
        </div>
      )}
    </CommandDialog>
  )
}
