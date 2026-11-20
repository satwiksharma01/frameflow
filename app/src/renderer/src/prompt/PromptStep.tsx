import { Plus } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { Described, SettingsView, ThinkRequest } from '@shared/types'
import { say } from '../shell/Toasts'
import { Figures, Label, PlanView } from './PlanView'
import { forgetFailure, think, thinker, useThought, type Done, type Start } from './thinking'

type Kind = 'footage' | 'assets' | 'music' | 'script' | 'looks'
const MATERIAL: [Kind, string][] = [
  ['footage', 'Recording'],
  ['assets', 'Pictures or clips'],
  ['music', 'Music'],
  ['script', 'Script'],
  ['looks', 'Look']
]
const NOTHING: Start = { kind: 'start', prompt: '', footage: [], assets: [], music: [], looks: [] }
const SECOND = 'h-10 rounded-lg border border-ink px-[18px] text-[13px] font-bold text-ink'
// The main action; off, it is drawn as the sketch draws it rather than faded.
const MAIN =
  'ml-auto h-10 flex-none rounded-lg px-[22px] text-[13px] font-bold disabled:bg-off disabled:text-quiet disabled:opacity-100'

const named = (path: string): string => path.split(/[\\/]/).pop() ?? path

/** The thinker's steps as they happen, numbered, the one it is on in ink. */
function Steps({ steps }: { steps: string[] }): React.JSX.Element {
  return (
    <ol aria-label="Plan steps" aria-live="polite" className="mt-[26px] text-[15px] leading-[2.1]">
      {steps.map((step, i) => {
        const now = i === steps.length - 1
        return (
          <li
            key={i}
            aria-current={now ? 'step' : undefined}
            className={cn('flex items-baseline gap-3', now ? 'font-medium text-ink' : 'text-quiet')}
          >
            <span className="w-[18px] flex-none text-[11px] font-normal text-quiet">
              {String(i + 1).padStart(2, '0')}
            </span>
            {now ? `${step}…` : step}
          </li>
        )
      })}
    </ol>
  )
}

interface Props {
  /** The video, or null for a new one, whose folder is made when its plan is first asked for. */
  folder: string | null
  /** A new video's folder is made and its plan is being written: the app opens it. */
  onCreated?(folder: string): void
  /** A job has ended, here or after the creator left: what it was, how it ended, and whether Approve
   *  replaced a storyboard. */
  onThought?(folder: string, kind: ThinkRequest['kind'], done: Done, replaced: boolean): void
  /** The plan was changed by hand, so its title may have. */
  onChanged?(): void
  onSettings?(): void
}

/** The prompt step: what the creator wants and their material on the left, the plan Frameflow writes
 *  from them on the right, and Approve, which has the storyboard written. */
export function PromptStep({
  folder,
  onCreated,
  onThought,
  onChanged,
  onSettings
}: Props): React.JSX.Element {
  const id = useId()
  const thought = useThought(folder)
  const [described, setDescribed] = useState<Described | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [view, setView] = useState<SettingsView | null>(null)
  // What the plan is written from; coming back to a video finds what it was last asked from.
  const [asked, setAsked] = useState<Start>(() => thought.start ?? NOTHING)
  const [words, setWords] = useState('')
  const [making, setMaking] = useState(false)
  const top = useRef<HTMLHeadingElement>(null) // the plan's heading, where the focus waits while a job runs
  const again = useRef<HTMLButtonElement>(null) // a failure's Try again or Open Settings

  const read = useCallback(() => {
    if (!folder) return
    window.frameflow.describe(folder).then(
      (d) => {
        setDescribed(d)
        setProblem(null) // a read caught half-written is past once one reads well
        // Asked from nothing in this run, the idea is the one the video was prepared from.
        setAsked((a) => (a === NOTHING ? { ...NOTHING, prompt: d.prompt ?? '' } : a))
      },
      (e: Error) => setProblem(e.message)
    )
  }, [folder])
  useEffect(read, [read])
  // Once a job ends, whichever screen began it, the plan is read again; a failed one left it as it was.
  // The focus goes on from the plan's heading, where a job leaves it, unless the creator has moved it.
  const was = useRef<boolean | null>(null) // null until the first look
  useEffect(() => {
    const before = was.current
    was.current = thought.running
    const free = document.activeElement === document.body || document.activeElement === top.current
    if (before === null) {
      if (thought.running && free) top.current?.focus() // opened on a job, as a new video is
    } else if (before && !thought.running) {
      if (thought.failure === null) read()
      if (free) (thought.failure === null ? top : again).current?.focus()
    }
  }, [thought.running, thought.failure, read])
  useEffect(() => {
    window.frameflow.settings().then(setView, () => {}) // without it, the page names no thinker
  }, [])

  const who = thinker(view)
  const plan = described?.plan ?? null
  const questions = plan?.open_questions?.length ?? 0
  const facts = plan?.facts?.length ?? 0
  const unopened = described?.plan_unopened ?? []
  const opened = facts - unopened.filter((n) => n <= facts).length
  const { running, failure, steps } = thought
  // Material from before this run is shown as it is: only files picked in this run can be sent. A plan
  // asked for with none keeps it; then the plan changes in words.
  const start = thought.start
  const picked =
    !!start &&
    (!!start.script ||
      start.footage.length + start.assets.length + start.music.length + start.looks.length > 0)
  const kept = picked ? null : described?.material
  const locked =
    !!kept &&
    (kept.script ||
      kept.footage.length + kept.assets.length + kept.music.length + kept.looks.length > 0)
  const loaded = !folder || described !== null
  const editable = loaded && !locked // nothing to change before the video is read
  const fresh = loaded && !plan && !running && failure === null // nothing asked yet
  // A draft, or an approved plan with no storyboard yet, as a chat leaves one.
  const approvable = !!described?.plan_is_draft || !!described?.no_storyboard

  /** Ask the thinker. Its end is told to the app even if the creator has left this screen by then. */
  const run = (to: string, request: ThinkRequest): void => {
    const replaced = !!described && !described.no_storyboard
    top.current?.focus() // the control that asked may go while it thinks
    void think(to, request).then((done) => {
      if (!done) return // replaced by a newer job, which says what it does
      if (done.changed) say(done.message ?? '')
      onThought?.(to, request.kind, done, replaced)
    })
  }
  const writePlan = async (): Promise<void> => {
    const request = { ...asked, prompt: asked.prompt.trim() }
    if (folder) return run(folder, request)
    setMaking(true)
    try {
      const made = await window.frameflow.newVideo(request.prompt)
      run(made, request)
      onCreated?.(made)
    } catch (e) {
      say((e as Error).message)
      setMaking(false)
    }
  }
  const pick = async (kind: Kind): Promise<void> => {
    const paths = await window.frameflow.chooseFiles(kind).catch((e: Error) => {
      say(e.message)
      return []
    })
    if (!paths.length) return
    setAsked((a) =>
      kind === 'script'
        ? { ...a, script: paths[0] }
        : { ...a, [kind]: [...a[kind], ...paths.filter((p) => !a[kind].includes(p))] }
    )
  }
  const added =
    locked && kept
      ? [
          ...kept.footage,
          ...kept.assets,
          ...kept.music,
          ...(kept.script ? ['Script'] : []),
          ...kept.looks
        ]
      : [
          ...asked.footage,
          ...asked.assets,
          ...asked.music,
          ...(asked.script ? [asked.script] : []),
          ...asked.looks
        ]

  const left = running
    ? thought.kind === 'approve' || thought.kind === 'change' // a change in words, from another step
      ? steps.length
        ? `${steps[steps.length - 1]}…`
        : ''
      : 'Writing the plan…'
    : failure !== null && !plan
      ? `${steps.length > 1 ? 'Prepared · ' : ''}The plan was not written`
      : plan
        ? questions
          ? `${questions} ${questions === 1 ? 'question' : 'questions'} left`
          : !approvable
            ? 'Approved. Change the plan to write a new storyboard.'
            : [
                'Prepared',
                'Plan written',
                opened && `${opened} ${opened === 1 ? 'fact' : 'facts'} checked`
              ]
                .filter(Boolean)
                .join(' · ')
        : fresh && who.name
          ? `Written by ${who.name}${who.here ? ', found on this PC' : ''}`
          : ''

  // The engine's agent and key problems all say where to fix them.
  const inSettings = failure?.includes('Settings')

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="grid min-h-0 flex-1 grid-cols-[420px_minmax(0,1fr)]">
        <div className="overflow-y-auto border-r px-7 pb-7 pt-7">
          <Label n={1} id={`${id}-want`}>
            What you want
          </Label>
          <Textarea
            aria-labelledby={`${id}-want`}
            placeholder="Say what you want: the video, who it is for, how long, and anything it must say."
            value={asked.prompt}
            readOnly={!editable}
            onChange={(e) => setAsked({ ...asked, prompt: e.target.value })}
            className="min-h-[250px] resize-none rounded-xl border-dim px-[18px] py-4 text-[17px] leading-[1.4] text-ink placeholder:text-quiet md:text-[17px] dark:bg-transparent"
          />
          <div className="mt-[22px]">
            <Label n={2} id={`${id}-material`}>
              Your material
            </Label>
            {editable && (
              <div className="flex flex-wrap gap-2">
                {MATERIAL.map(([kind, name]) => (
                  <Button
                    key={kind}
                    variant="ghost"
                    onClick={() => void pick(kind)}
                    className="h-8 gap-2 rounded-md border border-dim px-3 text-[12px] font-normal text-ink"
                  >
                    <Plus aria-hidden className="size-3.5" />
                    {name}
                  </Button>
                ))}
              </div>
            )}
            {added.length ? (
              <ul aria-labelledby={`${id}-material`} className="mt-3 text-[12px] leading-[1.6]">
                {added.map((path, i) => (
                  <li key={i} title={path} className="truncate">
                    {named(path)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-[12px] leading-[1.4] text-quiet">
                Nothing added. Frameflow makes it from titles, graphics and a voiceover.
              </p>
            )}
          </div>
          {/* Not over a storyboard: preparing again would replace the material it was written from. */}
          {!running &&
            editable &&
            (plan || failure !== null) &&
            (!described || described.no_storyboard) && (
              <Button
                variant="ghost"
                disabled={!asked.prompt.trim()}
                onClick={() => void writePlan()}
                className="mt-[22px] h-8 rounded-none border-b border-dim px-0 text-[12px] font-normal text-quiet hover:bg-transparent hover:text-ink"
              >
                Write the plan again from this
              </Button>
            )}
        </div>

        <section aria-labelledby={`${id}-plan`} className="overflow-y-auto px-8 pb-10 pt-7">
          <Label n={3} id={`${id}-plan`} ref={top}>
            The plan
          </Label>
          {problem && (
            <p role="alert" className="select-text text-[13px]">
              {problem}
            </p>
          )}
          {failure !== null && !running && (
            <div className="mb-[26px] mt-[26px]">
              {inSettings ? (
                <p
                  role="alert"
                  className="select-text rounded-lg border border-dim px-[18px] py-4 text-[13px] leading-[1.5]"
                >
                  {failure}
                </p>
              ) : (
                <div
                  role="alert"
                  className="rounded-lg border border-dim px-[18px] py-4 text-[13px] leading-[1.5]"
                >
                  <p className="text-signal-ink">
                    {thought.kind === 'approve'
                      ? 'The storyboard could not be written.'
                      : 'The plan could not be written.'}
                  </p>
                  <p className="mt-1.5 select-text whitespace-pre-wrap text-quiet">{failure}</p>
                </div>
              )}
              <Button
                ref={again}
                variant="ghost"
                onClick={() =>
                  inSettings ? onSettings?.() : thought.request && run(folder!, thought.request)
                }
                className={cn(SECOND, 'mt-3.5')}
              >
                {inSettings ? 'Open Settings' : 'Try again'}
              </Button>
            </div>
          )}
          {running ? (
            <>
              <Figures plan={plan} />
              <Steps steps={steps} />
              <p className="mt-3.5 text-[12px] text-quiet">
                You can leave; you will be told when it is done.
              </p>
            </>
          ) : plan ? (
            <PlanView
              folder={folder!}
              plan={plan}
              unopened={unopened}
              by={who.name}
              searches={who.searches}
              onChanged={(d) => {
                setDescribed(d)
                forgetFailure(folder!)
                onChanged?.()
              }}
              onAsk={(request) => run(folder!, request)}
            />
          ) : (
            fresh && (
              <>
                <Figures plan={null} />
                <p className="mt-3.5 text-[12px] text-quiet">
                  Frameflow writes the plan from your idea and your material. Nothing is made until
                  you approve it.
                </p>
              </>
            )
          )}
        </section>
      </div>

      <footer className="flex h-[60px] flex-none items-center gap-4 border-t px-6 text-[12px] text-quiet">
        <p aria-live="polite" className="min-w-0 truncate">
          {left}
        </p>
        {plan && (
          <Input
            aria-label="Change the plan in words"
            placeholder="Change the plan in words…"
            value={words}
            disabled={running}
            onChange={(e) => setWords(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== 'Enter' || e.nativeEvent.isComposing || !words.trim()) return
              e.preventDefault()
              run(folder!, { kind: 'plan-change', words: words.trim() })
              setWords('')
            }}
            className="h-10 max-w-[520px] flex-1 rounded-lg border-dim px-3.5 text-[13px] text-ink placeholder:text-quiet md:text-[13px] dark:bg-transparent"
          />
        )}
        {fresh ? (
          <Button
            disabled={!asked.prompt.trim() || making}
            onClick={() => void writePlan()}
            className={MAIN}
          >
            Write the plan
          </Button>
        ) : (
          (loaded || running) && ( // not until the video is read, which may have no plan yet
            <Button
              disabled={!plan || running || questions > 0 || !approvable}
              onClick={() => run(folder!, { kind: 'approve' })}
              className={MAIN}
            >
              Approve and write the storyboard
            </Button>
          )
        )}
      </footer>
    </div>
  )
}
