// A video's storyboard and the creator's changes to it. Changes go to the engine one at a time, each with
// the version the one before it produced, so none is refused as made against an old storyboard and none
// is lost. Only a move shows before the engine answers, so a dropped scene does not jump back.
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import type { Described, EditAnswer, EditOp } from '@shared/types'
import { say } from '../shell/say'

export type EditResult = { ok: true; notes: string[] } | { ok: false; refused: string }

export interface StoryboardState {
  status: 'loading' | 'failed' | 'ready'
  described: Described | null
  message: string | null
  /** A change is on its way to the engine. */
  busy: boolean
  edit(op: EditOp, toast?: string): Promise<EditResult>
  undo(): Promise<void>
  redo(): Promise<void>
  reload(): void
}

/** Which scene is selected after a change. */
export function selectAfter(op: EditOp, selected: number, count: number): number {
  if (op.op === 'move') return op.to
  if (op.op === 'delete') return Math.min(selected, count - 1)
  if (op.op === 'add') return op.after + 1
  return selected
}

/** The scenes in their new order, numbered again, while the engine makes the move. */
function moved(described: Described, from: number, to: number): Described {
  const scenes = [...described.scenes]
  const [scene] = scenes.splice(from - 1, 1)
  scenes.splice(to - 1, 0, scene)
  return { ...described, scenes: scenes.map((s, i) => ({ ...s, number: i + 1 })) }
}

export function useStoryboard(folder: string): StoryboardState {
  const [status, setStatus] = useState<StoryboardState['status']>('loading')
  const [described, setDescribed] = useState<Described | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(0)
  const latest = useRef<Described | null>(null) // what the next change is made against
  const queue = useRef<Promise<unknown>>(Promise.resolve())

  const show = useCallback((d: Described) => {
    latest.current = d
    setDescribed(d)
  }, [])

  const reload = useCallback(
    () =>
      window.frameflow.describe(folder).then(
        (d) => {
          show(d)
          setStatus('ready')
        },
        (e: Error) => {
          setMessage(e.message)
          setStatus('failed')
        }
      ),
    [folder, show]
  )
  // Another video is read afresh: it is loading from the first look at it.
  const [shownFolder, setShownFolder] = useState(folder)
  if (shownFolder !== folder) {
    setShownFolder(folder)
    setStatus('loading')
  }
  useEffect(() => {
    latest.current = null
    queue.current = Promise.resolve()
    void reload()
  }, [reload])

  /** Run `send` after every change before it, against the storyboard those changes left. */
  const enqueue = useCallback(<T>(send: (version: string) => Promise<T>): Promise<T> => {
    const run = queue.current.then(() => send(latest.current?.version ?? ''))
    queue.current = run.catch(() => {})
    setBusy((n) => n + 1)
    return run.finally(() => setBusy((n) => n - 1))
  }, [])

  const settle = useCallback(
    async (
      answer: EditAnswer,
      before: Described | null,
      undo: () => Promise<void>,
      said?: string
    ) => {
      if ('refused' in answer) {
        if (answer.changed) {
          say(answer.refused)
          await reload()
        } else if (before) {
          show(before) // a move shown early goes back
        }
        return { ok: false as const, refused: answer.refused }
      }
      show(answer.described)
      if (said) {
        say(said, { description: answer.notes.join(' ') || undefined, undo: () => void undo() })
      } else if (answer.notes.length) {
        say(answer.notes.join(' '))
      } else {
        toast.dismiss('edit') // what it said, and its Undo, are about a change that is no longer the last
      }
      return { ok: true as const, notes: answer.notes }
    },
    [reload, show]
  )

  const step = useCallback(
    (which: 'undo' | 'redo') =>
      enqueue(async (version) => {
        const now = latest.current
        if (!now || !(which === 'undo' ? now.can_undo : now.can_redo)) return
        const answer = await window.frameflow[which](folder, version).catch(
          (e: Error): EditAnswer => ({ refused: e.message, changed: false })
        )
        if ('refused' in answer) say(answer.refused)
        await settle(answer, null, async () => {})
      }),
    [enqueue, folder, settle]
  )
  const undo = useCallback(() => step('undo'), [step])
  const redo = useCallback(() => step('redo'), [step])

  const edit = useCallback(
    (op: EditOp, said?: string): Promise<EditResult> => {
      let before: Described | null = null
      if (op.op === 'move' && latest.current) {
        before = latest.current
        show(moved(latest.current, op.from, op.to))
      }
      return enqueue(async (version) => {
        const answer = await window.frameflow
          .edit(folder, op, version)
          .catch((e: Error): EditAnswer => ({ refused: e.message, changed: false }))
        return settle(answer, before, undo, said)
      })
    },
    [enqueue, folder, settle, show, undo]
  )

  return {
    status,
    described,
    message,
    busy: busy > 0,
    edit,
    undo,
    redo,
    reload: () => void reload()
  }
}
