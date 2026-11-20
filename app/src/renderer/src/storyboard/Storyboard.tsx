import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { rectSortingStrategy, SortableContext } from '@dnd-kit/sortable'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { CommandPalette } from '../shell/CommandPalette'
import { say } from '../shell/Toasts'
import { ChangeInWords, type ChangeInWordsHandle } from '../words/ChangeInWords'
import { AddScene } from './AddScene'
import { ChapterHeading } from './ChapterHeading'
import { DetailsPanel, type DetailsPanelHandle } from './DetailsPanel'
import { FiguresLine } from './FiguresLine'
import { actionFor, inTextField, type Action } from './keys'
import { toView, type SectionView } from './model'
import { moveOp } from './reorder'
import { SceneModule } from './SceneModule'
import { SectionIndex } from './SectionIndex'
import { selectAfter, useStoryboard, type EditResult, type StoryboardState } from './useStoryboard'
import type { EditOp, NewScene } from '@shared/types'

export function Notice({
  title,
  children
}: {
  title: string
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <div className="grid flex-1 place-items-center p-8">
      <div className="w-full max-w-lg">
        <h2 className="text-xl font-bold tracking-[-0.015em]">{title}</h2>
        {children}
      </div>
    </div>
  )
}

function Command({ children }: { children: string }): React.JSX.Element {
  return (
    <code className="mt-3 block select-text break-all rounded-md border px-3 py-2 text-[13px] text-quiet">
      {children}
    </code>
  )
}

/** The storyboard's shape while it loads: rules and frames, nothing that spins. */
function Loading(): React.JSX.Element {
  return (
    <div aria-busy="true" aria-label="Loading the storyboard" className="flex-1 px-7 py-6">
      <div className="h-10 w-72 animate-pulse rounded-md bg-plain" />
      <div className="mt-10 grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-5">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="border-t pt-2.5">
            <div className="h-4 w-16 animate-pulse rounded-sm bg-plain" />
            <div className="mt-2 flex gap-3">
              <div className="aspect-[9/16] w-[88px] animate-pulse rounded-md bg-plain" />
              <div className="h-4 flex-1 animate-pulse rounded-sm bg-plain" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

interface Props {
  folder: string
  /** The scene to open on, when the creator comes from another step; it takes the focus once drawn. */
  initialSelected?: number
  /** Told the selected scene as it changes, so another step can come back to it. */
  onSelected?(scene: number): void
  /** What sits in the footer: the whole-video controls and Build, given the storyboard's state, with the
   *  field that changes it in words to place before Build. */
  footer?: (state: StoryboardState, words: React.ReactNode) => React.ReactNode
  /** Opens the settings page; the command palette offers it. */
  onSettings?(): void
}

export function Storyboard({
  folder,
  initialSelected,
  onSelected,
  footer,
  onSettings
}: Props): React.JSX.Element | null {
  const state = useStoryboard(folder)
  const [selected, setSelected] = useState(initialSelected ?? 1)
  const scenesBox = useRef<HTMLDivElement>(null)
  useEffect(() => setSelected(initialSelected ?? 1), [folder, initialSelected])
  useEffect(() => onSelected?.(selected), [selected, onSelected])
  // A small movement first, so a click still selects and only a deliberate drag moves.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }))

  const view = useMemo(
    () => (state.status === 'ready' && state.described ? toView(state.described) : null),
    [state.status, state.described]
  )
  const scenes = useMemo(() => view?.sections.flatMap((s) => s.scenes) ?? [], [view])

  // A scene chosen from the keyboard takes the focus once it has been drawn as selected, as does the
  // scene that takes a deleted one's place, and the scene opened on from another step.
  const focusSelected = useRef(initialSelected !== undefined)
  useEffect(() => {
    if (!focusSelected.current || scenes.length === 0) return // none drawn yet while it loads
    focusSelected.current = false
    const element = scenesBox.current?.querySelector<HTMLElement>(`[data-scene="${selected}"]`)
    element?.focus()
    element?.scrollIntoView({ block: 'nearest' })
  }, [selected, scenes])

  const select = (number: number, focus = false): void => {
    const next = Math.min(Math.max(number, 1), scenes.length)
    focusSelected.current = focus && next !== selected
    setSelected(next)
  }

  const details = useRef<DetailsPanelHandle>(null)
  const words = useRef<ChangeInWordsHandle>(null)
  // Every change goes through here, so the selection follows it: a moved scene stays selected, a deleted
  // one gives way to the scene that took its place, and an added one is selected.
  // A refusal with no field of its own to show it in is said in a toast, as is one whose field went with
  // its scene's panel before the answer came (the words are sent when the creator clicks another scene).
  const shown = useRef(selected)
  shown.current = selected
  const change = async (op: EditOp, said?: string): Promise<EditResult> => {
    setSelected(selectAfter(op, selected, scenes.length))
    const result = await state.edit(op, said)
    const inField =
      op.op === 'add' || ((op.op === 'words' || op.op === 'over') && op.number === shown.current)
    if (!result.ok && !inField) say(result.refused)
    return result
  }

  const keys = scenes.map((s) => s.key)
  const number = (key: unknown): number => keys.indexOf(String(key)) + 1
  const dropped = ({ active, over }: DragEndEvent): void => {
    const op = over && moveOp(keys, String(active.id), String(over.id))
    if (!op || op.op !== 'move') return
    void change(op, `Scene ${op.from} moved`)
  }

  const [palette, setPalette] = useState(false)

  /** What a key, or the palette, does to the selected scene. */
  const perform = (action: Action): void => {
    // How many scenes sit in a row, from the grid as it is laid out now.
    const grid = scenesBox.current?.querySelector('[data-grid]')
    const columns =
      (grid && getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length) || 3
    const moves: Partial<Record<Action, number>> = {
      next: selected + 1,
      previous: selected - 1,
      down: selected + columns,
      up: selected - columns,
      first: 1,
      last: scenes.length
    }
    const to = moves[action]
    if (to !== undefined) return select(to, true)
    if (action === 'move-earlier' || action === 'move-later') {
      const place = selected + (action === 'move-later' ? 1 : -1)
      if (place < 1 || place > scenes.length) return
      focusSelected.current = true
      void change({ op: 'move', from: selected, to: place }, `Scene ${selected} moved`)
    } else if (action === 'delete') {
      focusSelected.current = true
      void change({ op: 'delete', number: selected }, `Scene ${selected} deleted`)
    } else if (action === 'edit-words') details.current?.focusWords()
    else if (action === 'undo') void state.undo()
    else if (action === 'redo') void state.redo()
    else if (action === 'palette') setPalette((open) => !open)
    else if (action === 'play') {
      const scene = scenes.find((s) => s.number === selected)
      if (details.current?.playing) details.current.stop()
      else if (state.described?.preview && scene && scene.start !== null && scene.seconds !== null)
        details.current?.play(scene.start, scene.start + scene.seconds)
      else say('Build the video to play its scenes.')
    }
  }

  // On the scene list, only a scene's own keys: a key pressed on a tile's button or a chapter's menu is
  // that control's.
  const onKeyDown = (event: React.KeyboardEvent): void => {
    if (!(event.target instanceof HTMLElement) || !event.target.hasAttribute('data-scene')) return
    const action = actionFor(event, false)
    if (!action || action === 'undo' || action === 'redo' || action === 'palette') return
    event.preventDefault()
    perform(action)
  }

  // Undo, redo and the palette work wherever the focus is, except in a field, which keeps its own Ctrl+Z.
  // Esc stops a scene playing, wherever the focus is.
  const latest = useRef(perform)
  latest.current = perform
  useEffect(() => {
    const onWindowKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') details.current?.stop()
      const action = actionFor(event, inTextField(event.target))
      if (action !== 'undo' && action !== 'redo' && action !== 'palette') return
      event.preventDefault()
      latest.current(action)
    }
    window.addEventListener('keydown', onWindowKey)
    return () => window.removeEventListener('keydown', onWindowKey)
  }, [])

  // Once a field is sent or let go from the keyboard, the keys work on the scenes again.
  const backToScene = (): void =>
    scenesBox.current?.querySelector<HTMLElement>(`[data-scene="${selected}"]`)?.focus()

  const added = (kind: NewScene['kind']): void => {
    if (kind === 'title') requestAnimationFrame(() => details.current?.focusTitle())
  }

  const jump = (section: SectionView): void => {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    scenesBox.current
      ?.querySelector(`[data-section="${section.number}"]`)
      ?.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' })
    if (section.scenes[0]) setSelected(section.scenes[0].number)
  }

  if (state.status === 'loading') return <Loading />
  if (state.status === 'failed') {
    return (
      <Notice title="Frameflow could not read this video">
        <p role="alert" className="mt-2 select-text whitespace-pre-wrap text-signal-ink">
          {state.message}
        </p>
        <p className="mt-4 text-quiet">It asked the engine:</p>
        <Command>{`python -m project.app_api describe "${folder}"`}</Command>
        <Button className="mt-5 h-10 rounded-lg px-5" onClick={() => state.reload()}>
          Try again
        </Button>
      </Notice>
    )
  }
  const described = state.described
  // A video with no storyboard has its prompt step instead: the step bar does not open this one.
  if (!described || described.no_storyboard || !view) return null

  const chapters = view.sections.some((s) => s.title !== null)
  const current = view.sections.find((s) => s.scenes.some((scene) => scene.number === selected))
  const chosen = scenes.find((s) => s.number === selected) ?? scenes[0]

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1">
        {chapters && (
          <SectionIndex sections={view.sections} current={current?.number ?? 1} onJump={jump} />
        )}
        <div ref={scenesBox} className="min-w-0 flex-1 overflow-y-auto px-7 pb-10 pt-6">
          <FiguresLine figures={view.figures} />
          <DndContext
            sensors={sensors}
            onDragEnd={dropped}
            accessibility={{
              screenReaderInstructions: {
                draggable:
                  'To move a scene, drag it with the pointer, or press Alt with the left or right arrow.'
              },
              announcements: {
                onDragStart: ({ active }) => `Picked up scene ${number(active.id)}.`,
                onDragOver: () => undefined,
                onDragEnd: ({ active, over }) =>
                  over && over.id !== active.id
                    ? `Scene ${number(active.id)} moved to number ${number(over.id)}.`
                    : `Scene ${number(active.id)} stays where it was.`,
                onDragCancel: ({ active }) => `Scene ${number(active.id)} stays where it was.`
              }
            }}
          >
            <SortableContext items={scenes.map((s) => s.key)} strategy={rectSortingStrategy}>
              <div
                role="listbox"
                aria-label="Scenes"
                aria-orientation="horizontal"
                onKeyDown={onKeyDown}
              >
                {view.sections.map((section) => (
                  <section
                    key={section.number}
                    data-section={section.number}
                    className="scroll-mt-4"
                  >
                    {section.title !== null && (
                      <ChapterHeading section={section} edit={change} onDone={backToScene} />
                    )}
                    <div
                      data-grid
                      className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-x-5 gap-y-6"
                      style={section.title === null ? { marginTop: 28 } : undefined}
                    >
                      {section.scenes.map((scene) => (
                        <SceneModule
                          key={scene.key}
                          scene={scene}
                          folder={folder}
                          aspect={described.aspect}
                          selected={scene.number === selected}
                          onSelect={() => select(scene.number)}
                        />
                      ))}
                      <AddScene
                        after={section.scenes.at(-1)?.number ?? 0}
                        edit={change}
                        onAdded={added}
                      />
                    </div>
                  </section>
                ))}
              </div>
            </SortableContext>
          </DndContext>
        </div>
        {chosen && (
          <DetailsPanel
            ref={details}
            scene={chosen}
            folder={folder}
            aspect={described.aspect}
            preview={described.preview}
            edit={change}
            onDone={backToScene}
          />
        )}
      </div>
      <CommandPalette
        open={palette}
        onOpenChange={setPalette}
        folder={folder}
        described={described}
        sections={view.sections}
        selected={chosen?.number ?? 1}
        act={perform}
        listen={() => details.current?.listen()}
        edit={change}
        goTo={(n) => select(n, true)}
        goToChapter={jump}
        onAdded={added}
        onClosed={backToScene}
        onSettings={onSettings}
        changeInWords={() => words.current?.focus()}
      />
      {footer && (
        <footer className="relative flex h-[60px] flex-none items-center gap-5 border-t px-6">
          {footer(
            state,
            <ChangeInWords
              ref={words}
              folder={folder}
              state={state}
              onDone={backToScene}
              onSettings={onSettings}
            />
          )}
        </footer>
      )}
    </div>
  )
}
