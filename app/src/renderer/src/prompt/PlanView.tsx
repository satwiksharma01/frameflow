import { useId, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { Described, Plan, ThinkRequest } from '@shared/types'
import { say } from '../shell/say'
import { clock } from '../storyboard/model'

const SHAPES: Plan['aspect'][] = ['16:9', '9:16', '1:1']
const FIELDS: ['title' | 'audience' | 'tone' | 'summary', string][] = [
  ['title', 'Title'],
  ['audience', 'For'],
  ['tone', 'Tone'],
  ['summary', 'What it says']
]
const SMALL = 'ml-1.5 text-[14px] font-medium tracking-normal text-quiet'
const QUIET_BUTTON =
  'h-8 px-2 text-[12px] font-normal text-quiet hover:bg-transparent hover:text-ink'
const LINE =
  'h-8 flex-1 rounded-md border-dim px-3 text-[12px] text-ink placeholder:text-quiet md:text-[12px] dark:bg-transparent'

const two = (n: number): string => String(n).padStart(2, '0')
const NEEDED = 'Needed fact: ' // how the plan marks a fact the thinker could not look up

/** A length typed as m:ss or in seconds. Anything else goes to the engine as typed, which says what is
 *  wrong with it, as it does for a row. */
function typedLength(text: string): number | string {
  const clocked = /^(\d+):([0-5]\d)$/.exec(text)
  if (clocked) return Number(clocked[1]) * 60 + Number(clocked[2])
  return /^\d+(\.\d+)?$/.test(text) ? Number(text) : text
}

/** A figure changed where it stands: a click opens it for typing, Enter sends it, Esc lets it go, and
 *  either way the focus comes back to the figure. */
function InPlace({
  label,
  said,
  change,
  value,
  field,
  onSave,
  children
}: {
  label: string
  /** The figure as it is read out, such as "1:00 minutes". */
  said: string
  /** What the control does, read after the figure, as the rows' Change buttons say it. */
  change: string
  value: string
  /** The field's own look, sized as the figure it stands in for. */
  field: string
  onSave(text: string): void
  children: React.ReactNode
}): React.JSX.Element {
  const [draft, setDraft] = useState<string | null>(null) // null while the figure is only shown
  const cancelled = useRef(false) // Esc: the blur that follows sends nothing
  const figure = useRef<HTMLButtonElement>(null)
  const back = (): void => void requestAnimationFrame(() => figure.current?.focus())
  const commit = (): void => {
    if (draft === null || cancelled.current) return
    setDraft(null)
    if (draft.trim() !== value) onSave(draft.trim())
  }
  return draft === null ? (
    <button
      ref={figure}
      type="button"
      onClick={() => {
        cancelled.current = false
        setDraft(value)
      }}
      // A 32 px target that leaves the figure where it stands.
      className="-my-[9px] cursor-text rounded-md py-[9px] outline-offset-4"
    >
      <span aria-hidden>{children}</span>
      {/* The name starts with what the figure shows (WCAG 2.5.3), then says what the control does. */}
      <span className="sr-only">
        {said}, {change}
      </span>
    </button>
  ) : (
    <Input
      aria-label={label}
      autoFocus
      spellCheck={false}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onFocus={(e) => e.currentTarget.select()}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
          e.preventDefault()
          e.currentTarget.blur() // which sends it
          back()
        } else if (e.key === 'Escape') {
          e.preventDefault()
          cancelled.current = true
          setDraft(null)
          back()
        }
      }}
      className={cn('rounded-md border-dim text-ink dark:bg-transparent', field)}
    />
  )
}

/** A part of the page by its number and name, small: hierarchy comes from the figures and the words. */
export function Label({
  n,
  id,
  children,
  ref
}: {
  n: number
  id: string
  children: string
  /** Given, the heading can hold the focus, as the plan's does while a job runs. */
  ref?: React.Ref<HTMLHeadingElement>
}): React.JSX.Element {
  return (
    <h2
      ref={ref}
      tabIndex={ref ? -1 : undefined}
      className="mb-2.5 flex items-baseline gap-2.5 text-[12px] font-normal text-quiet"
    >
      <b className="font-bold text-ink">{two(n)}</b>
      <span id={id}>{children}</span>
    </h2>
  )
}

/** The plan in figures (its length, its shape and its kind, its facts), then the storyboard to come as
 *  ghost rules across the width. Dashes until there is a plan; the length, the shape and the kind are
 *  changed on their figures once there is. */
export function Figures({
  plan,
  by,
  onEdit
}: {
  plan: Plan | null
  by?: string | null
  onEdit?(fields: Record<string, unknown>): void
}): React.JSX.Element {
  const seconds = plan?.target_seconds ?? 0
  const long = !plan || seconds >= 60 // as the storyboard's figures read: a minute or more in minutes
  const length = long ? clock(seconds) : String(seconds)
  const facts = plan?.facts?.length ?? 0
  const lengthFigure = (
    <>
      <span className={cn(!plan && 'text-faint')}>{plan ? length : '–'}</span>
      <small className={SMALL}> {long ? 'minutes' : 'seconds'}</small>
    </>
  )
  return (
    <>
      <div
        role="group"
        aria-label="The plan in figures"
        className="flex items-baseline gap-[34px] text-[40px] font-bold leading-none tracking-[-0.03em] tabular-nums"
      >
        <div>
          {plan && onEdit ? (
            <InPlace
              label="Length"
              said={`${length} ${long ? 'minutes' : 'seconds'}`}
              change="change length"
              value={length}
              field="h-auto w-[5ch] px-1 py-0 text-[40px] font-bold leading-none tracking-[-0.03em] md:text-[40px]"
              onSave={(text) => {
                // The same length typed another way is no change: an approved plan stays approved.
                const typed = typedLength(text)
                if (typed !== seconds) onEdit({ target_seconds: typed })
              }}
            >
              {lengthFigure}
            </InPlace>
          ) : (
            lengthFigure
          )}
        </div>
        <div className="flex items-baseline">
          {!plan ? (
            <span className="text-faint">–</span>
          ) : onEdit ? (
            <Select value={plan.aspect} onValueChange={(aspect) => onEdit({ aspect })}>
              <SelectTrigger
                aria-label="Shape"
                className="h-auto gap-1.5 rounded-md border-0 bg-transparent p-0 text-[40px] font-bold shadow-none data-[size=default]:h-auto dark:bg-transparent dark:hover:bg-transparent"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="rounded-xl">
                {SHAPES.map((shape) => (
                  <SelectItem key={shape} value={shape}>
                    {shape}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            plan.aspect
          )}
          <small className={SMALL}>
            {' '}
            {plan && onEdit ? (
              <InPlace
                label="Kind"
                said={plan.format}
                change="change kind"
                value={plan.format}
                field="h-8 w-[20ch] px-2 text-[14px] font-medium md:text-[14px]"
                onSave={(format) => onEdit({ format })}
              >
                {plan.format}
              </InPlace>
            ) : plan ? (
              plan.format
            ) : (
              'shape'
            )}
          </small>
        </div>
        {facts > 0 && (
          <div>
            {facts}
            <small className={SMALL}> {facts === 1 ? 'fact' : 'facts'}</small>
          </div>
        )}
        {plan && by && (
          <span className="ml-auto text-[12px] font-normal tracking-normal text-quiet">
            Written by {by}
          </span>
        )}
      </div>
      {/* The storyboard to come: no scene exists yet, so its rules are ghosts across the target length. */}
      <div aria-hidden className="mb-1.5 mt-[18px] flex gap-0.5">
        {Array.from({ length: 12 }, (_, i) => (
          <i key={i} className="h-[3px] flex-1 rounded-[2px] bg-dim" />
        ))}
      </div>
      <div className="flex justify-between gap-4 text-[12px] text-quiet">
        <span>0:00</span>
        <span>The storyboard fills this when you approve</span>
        <span>{plan ? clock(seconds) : ''}</span>
      </div>
    </>
  )
}

/** One field of the plan: shown as it is, changed in place with Change, sent with Enter, left with Esc. */
function Field({
  label,
  value,
  onSave
}: {
  label: string
  value: string
  onSave(text: string): Promise<void>
}): React.JSX.Element {
  const [draft, setDraft] = useState<string | null>(null) // null while the field is only shown
  const cancelled = useRef(false) // Esc: the blur that follows sends nothing
  const change = useRef<HTMLButtonElement>(null)
  const open = (): void => {
    cancelled.current = false
    setDraft(value)
  }
  const commit = (): void => {
    if (draft === null || cancelled.current) return
    setDraft(null)
    if (draft.trim() !== value) void onSave(draft.trim())
  }
  // Sent or let go from the keyboard, the focus goes back to Change rather than to the page.
  const back = (): void => void requestAnimationFrame(() => change.current?.focus())
  return (
    <div className="grid grid-cols-[110px_1fr_70px] border-t">
      <dt className="py-[11px] text-[12px] text-quiet">{label}</dt>
      <dd className="min-w-0 py-[11px] text-[15px] leading-[1.35]">
        {draft === null ? (
          <span className="block select-text first-letter:uppercase">{value}</span>
        ) : (
          <Textarea
            aria-label={label}
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value.replace(/\n/g, ' '))}
            onFocus={(e) => e.currentTarget.select()}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
                e.preventDefault()
                e.currentTarget.blur() // which sends it
                back()
              } else if (e.key === 'Escape') {
                e.preventDefault()
                cancelled.current = true
                setDraft(null)
                back()
              }
            }}
            className="-mx-2 -my-1 min-h-0 w-[calc(100%+16px)] resize-none rounded-md border-dim px-2 py-1 text-[15px] leading-[1.35] text-ink md:text-[15px] dark:bg-transparent"
          />
        )}
      </dd>
      <dd className="py-[11px] text-right">
        <Button
          ref={change}
          variant="ghost"
          aria-label={`Change ${label}`}
          onClick={open}
          className={cn(QUIET_BUTTON, '-mr-2 -my-1.5')}
        >
          Change
        </Button>
      </dd>
    </div>
  )
}

/** An open question, answered in a line or removed. A fact the thinker could not look up asks instead
 *  for its page and the words on it, which go to the thinker as the answer, or Drop. */
function Question({
  n,
  text,
  fact,
  why,
  onAnswer,
  onRemove
}: {
  n: number
  text: string
  fact: boolean
  /** Say that the key cannot look things up, when that is why the fact is asked for. */
  why: boolean
  onAnswer(words: string): void
  onRemove(): void
}): React.JSX.Element {
  const [line, setLine] = useState('')
  const [page, setPage] = useState('')
  const [words, setWords] = useState('')
  const send = (e: React.KeyboardEvent): void => {
    if (e.key !== 'Enter' || e.nativeEvent.isComposing) return
    e.preventDefault()
    if (!fact && line.trim()) onAnswer(line.trim())
    if (fact && page.trim() && words.trim())
      onAnswer(`Page: ${page.trim()} — Words: ${words.trim()}`)
  }
  return (
    <li className="grid grid-cols-[30px_1fr] gap-x-3 border-t py-3">
      <b className="text-[15px]">{two(n)}</b>
      <div className="min-w-0">
        <p className="select-text text-[15px] leading-[1.35]">
          {fact ? text.charAt(NEEDED.length).toUpperCase() + text.slice(NEEDED.length + 1) : text}
        </p>
        {fact && why && (
          <p className="mt-1 text-[12px] text-quiet">
            This key cannot look things up, so give the page and the words on it, or drop it.
          </p>
        )}
        <div className="mt-2.5 flex items-center gap-2">
          {fact ? (
            <>
              <Input
                aria-label="The page’s address"
                placeholder="The page’s address"
                spellCheck={false}
                value={page}
                onChange={(e) => setPage(e.target.value)}
                onKeyDown={send}
                className={LINE}
              />
              <Input
                aria-label="The words on it"
                placeholder="The words on it"
                value={words}
                onChange={(e) => setWords(e.target.value)}
                onKeyDown={send}
                className={LINE}
              />
            </>
          ) : (
            <Input
              aria-label="Answer in a line"
              placeholder="Answer in a line"
              value={line}
              onChange={(e) => setLine(e.target.value)}
              onKeyDown={send}
              className={LINE}
            />
          )}
          <Button variant="ghost" onClick={onRemove} className={QUIET_BUTTON}>
            {fact ? 'Drop' : 'Remove'}
          </Button>
        </div>
      </div>
    </li>
  )
}

interface Props {
  folder: string
  plan: Plan
  /** The facts (from 1) whose page Frameflow could not open. */
  unopened: number[]
  /** Who writes the plan, as the settings name it. */
  by: string | null
  /** Whether that thinker looks facts up on the web: of the keys, only Anthropic's does. */
  searches: boolean
  /** The video after a change by hand. */
  onChanged(described: Described): void
  /** A question answered, for the thinker to fold into the plan. */
  onAsk(request: ThinkRequest): void
}

/** The plan written: its figures, its fields, each changed by hand, its open questions and its facts. */
export function PlanView({
  folder,
  plan,
  unopened,
  by,
  searches,
  onChanged,
  onAsk
}: Props): React.JSX.Element {
  const edit = (fields: Record<string, unknown>): Promise<void> =>
    window.frameflow.editPlan(folder, fields).then(onChanged, (e: Error) => say(e.message))
  const questions = plan.open_questions ?? []
  const facts = plan.facts ?? []
  const marked = facts.some((_, i) => unopened.includes(i + 1))
  return (
    <>
      <Figures plan={plan} by={by} onEdit={(fields) => void edit(fields)} />
      <dl className="mt-[22px]">
        {FIELDS.map(([field, label]) => (
          <Field
            key={field}
            label={label}
            value={plan[field]}
            onSave={(text) => edit({ [field]: text })}
          />
        ))}
      </dl>
      {questions.length > 0 && (
        <Part n={4} name="Open questions" note="answer or remove each to approve">
          <ol>
            {questions.map((question, i) => (
              <Question
                key={`${i} ${question}`}
                n={i + 1}
                text={question}
                fact={question.startsWith(NEEDED)}
                why={!searches}
                onAnswer={(words) => onAsk({ kind: 'answer', question: i + 1, words })}
                onRemove={() => void edit({ remove_question: i + 1 })}
              />
            ))}
          </ol>
        </Part>
      )}
      {facts.length > 0 && (
        <Part
          n={questions.length ? 5 : 4}
          name="Facts"
          note={marked ? undefined : 'each opened on its page'}
        >
          <ol>
            {facts.map((fact, i) => (
              <li
                key={i}
                className="grid grid-cols-[30px_1fr_120px] gap-x-3 border-t py-[9px] text-[15px]"
              >
                <b>{two(i + 1)}</b>
                <div className="min-w-0 select-text">
                  <p className="leading-[1.3]">{fact.claim}</p>
                  <p className="mt-1 text-[12px] text-quiet">“{fact.quote}”</p>
                  {unopened.includes(i + 1) && (
                    <p className="mt-1 text-[12px] text-quiet">
                      Frameflow could not open this page.
                    </p>
                  )}
                </div>
                <span className="text-right text-[12px] text-quiet">{fact.source}</span>
              </li>
            ))}
          </ol>
        </Part>
      )}
    </>
  )
}

function Part({
  n,
  name,
  note,
  children
}: {
  n: number
  name: string
  note?: string
  children: React.ReactNode
}): React.JSX.Element {
  const id = useId()
  return (
    <section aria-labelledby={id}>
      <h3 className="mb-1 mt-5 flex items-baseline gap-2.5 text-[15px] font-bold">
        <b className="text-[12px]">{two(n)}</b>
        <span id={id}>{name}</span>
        <span className="ml-auto text-[12px] font-normal text-quiet">{note}</span>
      </h3>
      {children}
    </section>
  )
}
