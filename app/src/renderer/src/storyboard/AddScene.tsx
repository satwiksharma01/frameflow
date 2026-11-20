import { Plus } from 'lucide-react'
import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import type { EditOp, NewScene } from '@shared/types'
import type { EditResult } from './useStoryboard'

interface Props {
  /** The number of the scene the new one comes after. */
  after: number
  edit(op: EditOp, toast?: string): Promise<EditResult>
  /** Called once a scene is added, with its kind. */
  onAdded?(kind: NewScene['kind']): void
}

/** The tile that ends a chapter: a title, a file of the creator's, or words from their recording. Words
 *  are typed in the tile itself, and a refusal stays there with them. */
export function AddScene({ after, edit, onAdded }: Props): React.JSX.Element {
  const [words, setWords] = useState<string | null>(null) // null until "From your recording…" is chosen
  const [waiting, setWaiting] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const field = useRef<HTMLInputElement>(null)

  const add = async (scene: NewScene): Promise<boolean> => {
    const result = await edit(
      { op: 'add', after, scene },
      scene.kind === 'title' ? undefined : 'Scene added'
    )
    if (!result.ok) {
      setProblem(result.refused)
      return false
    }
    onAdded?.(scene.kind)
    return true
  }
  const addFile = async (): Promise<void> => {
    const path = await window.frameflow.chooseFile()
    if (path) await add({ kind: 'file', path })
  }
  const addWords = async (): Promise<void> => {
    if (!words?.trim() || waiting) return
    setWaiting(true)
    setProblem(null)
    const added = await add({ kind: 'recording', words: words.trim() })
    setWaiting(false)
    if (added) setWords(null)
  }

  return (
    <div className="relative border-t pt-2.5">
      {words === null ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              className="h-9 rounded-md px-2.5 text-[13px] text-quiet hover:text-ink"
            >
              <Plus aria-hidden />
              Add a scene
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="rounded-xl">
            <DropdownMenuItem onSelect={() => void add({ kind: 'title', text: 'New title' })}>
              A title
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void addFile()}>A file of yours…</DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => {
                setProblem(null)
                setWords('')
                requestAnimationFrame(() => field.current?.focus())
              }}
            >
              From your recording…
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <div className="grid gap-1.5">
          <label className="text-[12px] text-quiet" htmlFor={`words-after-${after}`}>
            Words you say in it
          </label>
          <div className="flex gap-1.5">
            <Input
              ref={field}
              id={`words-after-${after}`}
              aria-label="Words you say in it"
              value={words}
              disabled={waiting}
              onChange={(e) => setWords(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.nativeEvent.isComposing) void addWords()
                if (e.key === 'Escape') setWords(null)
              }}
              className="h-8 rounded-md text-[13px]"
            />
            <Button
              type="button"
              onClick={() => void addWords()}
              disabled={waiting}
              className="h-8 rounded-md px-3 text-[13px]"
            >
              Add
            </Button>
          </div>
          {waiting && <p className="text-[12px] text-quiet">Finding it in your recording…</p>}
        </div>
      )}
      {problem && (
        <p role="alert" className="mt-1.5 text-[12px] text-signal-ink">
          {problem}
        </p>
      )}
    </div>
  )
}
