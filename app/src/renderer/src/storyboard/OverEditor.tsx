import { Plus, X } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'
import type { Broll, Card, EditOp } from '@shared/types'
import type { SceneView } from './model'
import type { EditResult } from './useStoryboard'

interface Props {
  scene: SceneView
  edit(op: EditOp, toast?: string): Promise<EditResult>
  /** Called once a field is sent with Enter, to give the focus back to the scenes. */
  onDone?(): void
}

/** A field that sends its change when it is left, or on Enter. */
function Field({
  label,
  value,
  onCommit,
  placeholder,
  inputMode
}: {
  label: string
  value: string
  onCommit(value: string): void
  placeholder?: string
  inputMode?: 'decimal'
}): React.JSX.Element {
  const [draft, setDraft] = useState(value)
  const [stored, setStored] = useState(value)
  if (value !== stored) {
    // The storyboard changed under the field (an undo, or the engine's own change): show it as it is now.
    setStored(value)
    setDraft(value)
  }
  return (
    <Input
      aria-label={label}
      placeholder={placeholder ?? label}
      value={draft}
      inputMode={inputMode}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => draft !== value && onCommit(draft.trim())}
      onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
      className="h-8 rounded-md px-2.5 text-[13px]"
    />
  )
}

/** One object's field, set or removed: an empty value removes it. */
function setField<T extends object>(item: T, key: keyof T, value: string | number | undefined): T {
  const next = { ...item }
  if (value === '' || value === undefined || Number.isNaN(value)) delete next[key]
  else (next as Record<keyof T, unknown>)[key] = value
  return next
}

function Remove({ label, onClick }: { label: string; onClick(): void }): React.JSX.Element {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label={label}
      onClick={onClick}
      className="rounded-md text-quiet"
    >
      <X aria-hidden />
    </Button>
  )
}

/** What pops up over a scene: its caption, its cards and, over footage, its B-roll. Every change sends the
 *  whole list, as the engine keeps it. */
export function OverEditor({ scene, edit, onDone }: Props): React.JSX.Element {
  const [problem, setProblem] = useState<string | null>(null)
  const send = async (op: EditOp): Promise<void> => {
    setProblem(null)
    const result = await edit(op)
    if (!result.ok) setProblem(result.refused)
  }
  const cards = (next: Card[]): Promise<void> =>
    send({ op: 'over', number: scene.number, cards: next })
  const broll = (next: Broll[]): Promise<void> =>
    send({ op: 'over', number: scene.number, broll: next })
  const changeCard = (i: number, key: keyof Card, value: string): void =>
    void cards(scene.cards.map((c, j) => (j === i ? setField(c, key, value) : c)))
  const changeBroll = (i: number, key: keyof Broll, value: string | number | undefined): void =>
    void broll(scene.broll.map((b, j) => (j === i ? setField(b, key, value) : b)))
  const addBroll = async (): Promise<void> => {
    const path = await window.frameflow.chooseFile()
    if (path) await broll([...scene.broll, { path }])
  }

  return (
    <section
      aria-label="Over it"
      className="mt-5"
      // A field sends itself on Enter (by blurring); the focus then goes back to the scenes.
      onKeyDown={(e) => e.key === 'Enter' && e.target instanceof HTMLInputElement && onDone?.()}
    >
      <h3 className="text-[12px] text-quiet">Over it</h3>
      <div className="mt-2">
        <Field
          label="Caption"
          placeholder="No caption"
          value={scene.caption ?? ''}
          onCommit={(caption) =>
            void send({ op: 'over', number: scene.number, caption: caption || null })
          }
        />
      </div>

      {scene.cards.map((card, i) => (
        <div key={`${i}-${card.kind}-${card.text}`} className="mt-3 grid gap-1.5 border-t pt-3">
          <div className="flex items-center gap-1.5">
            <Select value={card.kind} onValueChange={(kind) => changeCard(i, 'kind', kind)}>
              <SelectTrigger
                aria-label="Kind of card"
                size="sm"
                className="h-8 w-36 rounded-md text-[13px]"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="product">Product</SelectItem>
                <SelectItem value="lower_third">Name on screen</SelectItem>
              </SelectContent>
            </Select>
            <span className="ml-auto" />
            <Remove
              label="Remove card"
              onClick={() => void cards(scene.cards.filter((_, j) => j !== i))}
            />
          </div>
          <Field
            label={card.kind === 'product' ? 'Product' : 'Name'}
            value={card.text}
            onCommit={(v) => v && changeCard(i, 'text', v)}
          />
          <Field
            label="Second line"
            value={card.subtitle ?? ''}
            onCommit={(v) => changeCard(i, 'subtitle', v)}
          />
          {card.kind === 'product' && (
            <Field
              label="Price"
              value={card.price ?? ''}
              onCommit={(v) => changeCard(i, 'price', v)}
            />
          )}
          <Field
            label="Pops up on"
            placeholder="Pops up on (words in this scene)"
            value={card.when ?? ''}
            onCommit={(v) => changeCard(i, 'when', v)}
          />
        </div>
      ))}
      <Button
        type="button"
        variant="ghost"
        onClick={() => void cards([...scene.cards, { kind: 'product', text: 'New card' }])}
        className="mt-2 h-8 rounded-md px-2 text-[13px]"
      >
        <Plus aria-hidden />
        Add a card
      </Button>

      {scene.kind === 'footage' && (
        <>
          {scene.broll.map((b, i) => (
            <div key={`${i}-${b.path}`} className="mt-3 grid gap-1.5 border-t pt-3">
              <div className="flex items-center gap-1.5">
                <span className="min-w-0 flex-1 truncate text-[13px]" title={b.path}>
                  B-roll: {b.path.split(/[\\/]/).pop()}
                </span>
                <Remove
                  label="Remove B-roll"
                  onClick={() => void broll(scene.broll.filter((_, j) => j !== i))}
                />
              </div>
              <Field
                label="Pops up on"
                placeholder="Pops up on (words in this scene)"
                value={b.when ?? ''}
                onCommit={(v) => changeBroll(i, 'when', v)}
              />
              <Field
                label="Seconds on screen"
                inputMode="decimal"
                value={b.duration === undefined ? '' : String(b.duration)}
                onCommit={(v) => changeBroll(i, 'duration', v ? Number(v) : undefined)}
              />
            </div>
          ))}
          <Button
            type="button"
            variant="ghost"
            onClick={() => void addBroll()}
            className="mt-1 h-8 rounded-md px-2 text-[13px]"
          >
            <Plus aria-hidden />
            Add B-roll…
          </Button>
        </>
      )}
      {problem && (
        <p role="alert" className="mt-2 text-[12px] text-signal-ink">
          {problem}
        </p>
      )}
    </section>
  )
}
