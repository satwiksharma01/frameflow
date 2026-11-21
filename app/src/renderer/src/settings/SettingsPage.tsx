import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { Settings, SettingsView } from '@shared/types'
import { Steps } from '../storyboard/BuildBar'

type Service = NonNullable<Settings['service']>

// The Model field's grey text. Only Anthropic has a default in the engine (project/thinkers.py); no
// model is named for the others, since a named one goes out of date.
const NAMED = 'The model’s name, as the service lists it'
const SERVICES: { id: Service; name: string; model: string }[] = [
  { id: 'anthropic', name: 'Anthropic', model: 'Frameflow’s default' },
  { id: 'openai', name: 'OpenAI', model: NAMED },
  { id: 'openrouter', name: 'OpenRouter', model: NAMED },
  { id: 'gemini', name: 'Gemini', model: NAMED },
  { id: 'custom', name: 'Another address', model: NAMED }
]

interface Tested {
  running: boolean
  steps: string[]
  /** The thinker that answered, as the engine named it. */
  ready?: string
  failure?: string
}
const UNTESTED: Tested = { running: false, steps: [] }

// What is kept: no empty model or address, and an address only for another address.
function kept(s: Settings): Settings {
  const out: Settings = { thinking: s.thinking }
  if (s.service) out.service = s.service
  if (s.model?.trim()) out.model = s.model.trim()
  if (s.service === 'custom' && s.baseUrl?.trim()) out.baseUrl = s.baseUrl.trim()
  return out
}

const RADIO =
  'flex-none cursor-pointer appearance-none rounded-full border-[1.5px] border-quiet [corner-shape:round] ' +
  'checked:border-ink checked:bg-ink checked:shadow-[inset_0_0_0_4px_var(--ground)] ' +
  'disabled:cursor-not-allowed disabled:border-dim'
const FIELD = 'h-10 rounded-lg border-dim px-3.5 text-[13px] md:text-[13px]'
const SECOND = 'h-10 rounded-lg border border-dim px-[18px] text-[13px] text-quiet'

/** One of the two ways Frameflow thinks: its radio button, its name and what it means, then its own controls. */
function Way({
  id,
  name,
  sub,
  checked,
  onChoose,
  children
}: {
  id: string
  name: string
  sub: string
  checked: boolean
  onChoose(): void
  children?: React.ReactNode
}): React.JSX.Element {
  return (
    <div className="grid grid-cols-[32px_1fr] gap-x-3 border-t py-4">
      <label htmlFor={id} className="flex h-8 cursor-pointer items-start pt-0.5">
        <input
          id={id}
          type="radio"
          name="way"
          checked={checked}
          onChange={onChoose}
          aria-describedby={`${id}-sub`}
          className={cn(RADIO, 'size-[18px]')}
        />
      </label>
      <div className="min-w-0">
        <h3 className="text-[15px] font-bold">
          <label htmlFor={id} className="cursor-pointer">
            {name}
          </label>
        </h3>
        <p id={`${id}-sub`} className="mt-1 text-[12px] text-quiet">
          {sub}
        </p>
        {children}
      </div>
    </div>
  )
}

/** Settings: how Frameflow thinks, with an agent on this PC or the creator's own API key. The key is
 *  typed here once and handed to the main process; this page is only ever told that one is kept. */
export function SettingsPage(): React.JSX.Element {
  const id = useId()
  const [view, setView] = useState<SettingsView | null>(null)
  const [draft, setDraft] = useState<Settings>({ thinking: 'auto' })
  const [key, setKey] = useState('')
  const [replacing, setReplacing] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [tested, setTested] = useState<Tested>(UNTESTED)
  const run = useRef(0) // the test whose steps and answer are shown; one started or outdated since is not

  useEffect(() => {
    // A fresh look for the agents: one installed since the app started is found here.
    window.frameflow.settings(true).then(
      (found) => {
        setView(found)
        setDraft(kept(found))
      },
      (e: Error) => setProblem(e.message)
    )
  }, [])

  const said = (e: Error): void => setProblem(e.message)
  /** An answer from a test of what the settings were no longer holds, nor does one still on its way. */
  const untest = (): void => {
    run.current++
    setTested(UNTESTED)
  }
  /** Changes the draft, and so what a test would be of. */
  const edit = (change: Partial<Settings>): Settings => {
    const next = { ...draft, ...change }
    setDraft(next)
    untest()
    setProblem(null)
    return next
  }
  const save = (s: Settings = draft): Promise<void> => window.frameflow.saveSettings(kept(s))
  /** A choice is kept as it is made. */
  const choose = (change: Partial<Settings>): void => void save(edit(change)).catch(said)

  if (!view) {
    return (
      <Frame>
        {problem && (
          <p role="alert" className="select-text border-t py-4 text-[13px]">
            {problem}
          </p>
        )}
      </Frame>
    )
  }

  const byKey = draft.thinking === 'key'
  const service = draft.service ?? 'anthropic'
  const suggested = SERVICES.find((s) => s.id === service)!.model
  const first = view.agents.find((a) => a.found)
  // Only Anthropic has a model of its own, and another address has to be typed.
  const missing =
    service === 'custom' && !draft.baseUrl?.trim()
      ? draft.model?.trim()
        ? 'Type the address first.'
        : 'Type the address and a model first.'
      : service !== 'anthropic' && !draft.model?.trim()
        ? 'Name a model first.'
        : null
  const typing = !view.hasKey || replacing
  // A model on this PC may need no key.
  const testable = !byKey || (!missing && (view.hasKey || service === 'custom'))

  const changeService = (next: Service): void => {
    setKey('')
    setReplacing(false)
    // The saved key was the other service's: until the answer comes, none is this one's to replace or forget.
    setView({ ...view, hasKey: false })
    // The model was the other service's too. Then ask whether a key is kept for this one.
    save(edit({ service: next, model: undefined }))
      .then(() => window.frameflow.settings())
      .then(setView, said)
  }
  const saveKey = async (): Promise<void> => {
    try {
      await save() // first, so the key is kept for the service on screen
      await window.frameflow.saveKey(key)
      setView({ ...view, hasKey: true })
      setReplacing(false)
      setProblem(null)
      untest() // an answer was about the key before this one
    } catch (e) {
      said(e as Error)
    } finally {
      setKey('') // the key is not held here once it has been sent
    }
  }
  const forget = (): void => {
    window.frameflow.forgetKey().then(() => {
      setView({ ...view, hasKey: false })
      untest()
    }, said)
  }
  const test = async (): Promise<void> => {
    const mine = ++run.current
    const shown = (): boolean => run.current === mine
    setTested({ running: true, steps: [] })
    let ok = false
    let ready = ''
    let failure = ''
    try {
      await save()
      await window.frameflow.testThinking((event) => {
        if (!shown()) return
        if (event.type === 'step') setTested((t) => ({ ...t, steps: [...t.steps, event.text] }))
        else if (event.type === 'detail') {
          if (event.text.startsWith('Ready: ')) ready = event.text.slice('Ready: '.length)
        } else if (event.type === 'done') {
          ok = event.ok
          failure = event.message ?? ''
        }
      })
    } catch (e) {
      failure = (e as Error).message
    }
    if (!shown()) return // replaced by a newer test, or of settings that have changed: not a failure
    setTested(
      ok
        ? { ...UNTESTED, ready }
        : { ...UNTESTED, failure: failure || 'The test stopped without saying why.' }
    )
  }

  const testButton = (
    <div className="flex items-center gap-4">
      <Button
        variant="ghost"
        disabled={tested.running || !testable}
        onClick={() => void test()}
        className="h-10 rounded-lg border border-ink px-[18px] text-[13px] font-bold text-ink disabled:border-dim disabled:text-faint disabled:opacity-100"
      >
        {tested.running ? 'Testing' : 'Test'}
      </Button>
      <Steps label="Test steps" steps={tested.steps} running={tested.running} failed={false} />
      {byKey && missing && <p className="text-[12px] text-quiet">{missing}</p>}
    </div>
  )
  const testAnswer = (
    <>
      {tested.ready !== undefined && (
        <p role="status" className="mt-3.5 select-text text-[13px]">
          {/* The engine names a service "Anthropic (model)"; the line reads "Anthropic, model". */}
          <b className="font-medium">Ready:</b> {tested.ready.replace(/ \((.+)\)$/, ', $1')}
          {/* An agent has its own web tools; of the services, only Anthropic's can search. */}
          {(!byKey || service === 'anthropic') && (
            <span className="text-[12px] text-quiet"> · can look facts up on the web</span>
          )}
        </p>
      )}
      {tested.failure && (
        <p role="alert" className="mt-3.5 select-text text-[13px]">
          {tested.failure}
        </p>
      )}
    </>
  )

  return (
    <Frame>
      <div role="radiogroup" aria-label="How Frameflow thinks">
        <Way
          id={`${id}-byagent`}
          name="An agent on this PC"
          sub="Uses your own plan with that agent. No key needed."
          checked={!byKey}
          onChoose={() => choose({ thinking: 'auto' })}
        >
          <div role="radiogroup" aria-label="Agents" className="mt-3">
            <Agent
              id={`${id}-auto`}
              name="Automatic"
              checked={draft.thinking === 'auto'}
              onChoose={() => choose({ thinking: 'auto' })}
            >
              {first ? `${first.name} (found on this PC)` : 'No agent found on this PC'}
            </Agent>
            {view.agents.map((agent) => (
              <Agent
                key={agent.id}
                id={`${id}-${agent.id}`}
                name={agent.name}
                disabled={!agent.found}
                checked={draft.thinking === `agent:${agent.id}`}
                onChoose={() => choose({ thinking: `agent:${agent.id}` as Settings['thinking'] })}
              >
                {agent.found ? (
                  <>
                    <b className="font-medium text-ink">Found</b>
                    {agent.version && ` · ${agent.version}`}
                  </>
                ) : (
                  'Not found'
                )}
              </Agent>
            ))}
          </div>
          {!byKey && (
            <>
              <div className="mt-3.5">{testButton}</div>
              {testAnswer}
            </>
          )}
        </Way>
        <Way
          id={`${id}-bykey`}
          name="Your own API key"
          sub={
            byKey
              ? 'Each use is billed to your account. The key is kept encrypted by Windows and never shown again.'
              : 'Anthropic, OpenAI, OpenRouter, Gemini, or any OpenAI-compatible address, such as a model on this PC through Ollama. Each use is billed to your account.'
          }
          checked={byKey}
          onChoose={() => choose({ thinking: 'key', service })}
        >
          {byKey && (
            <>
              <div className="mt-3.5 grid max-w-[640px] grid-cols-[110px_1fr] items-center gap-x-4 gap-y-2.5 text-[12px] text-quiet">
                <label htmlFor={`${id}-service`}>Service</label>
                <Select value={service} onValueChange={changeService}>
                  <SelectTrigger
                    id={`${id}-service`}
                    className={cn(FIELD, 'w-full text-ink data-[size=default]:h-10')}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl">
                    {SERVICES.map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {typing ? (
                  <>
                    <label htmlFor={`${id}-key`}>Key</label>
                    <div className="flex items-center gap-2.5">
                      <Input
                        id={`${id}-key`}
                        type="password"
                        autoComplete="off"
                        spellCheck={false}
                        autoFocus={replacing}
                        value={key}
                        onChange={(e) => setKey(e.target.value)}
                        className={cn(FIELD, 'text-ink')}
                      />
                      <Button
                        variant="ghost"
                        disabled={!key.trim() || !!missing}
                        onClick={() => void saveKey()}
                        className={cn(SECOND, 'text-ink disabled:text-faint disabled:opacity-100')}
                      >
                        Save
                      </Button>
                      {replacing && (
                        <Button
                          variant="ghost"
                          onClick={() => {
                            setKey('')
                            setReplacing(false)
                          }}
                          className={SECOND}
                        >
                          Cancel
                        </Button>
                      )}
                    </div>
                  </>
                ) : (
                  <>
                    <span>Key</span>
                    <div className="flex items-center gap-3.5">
                      <span>A key is saved</span>
                      <Button variant="ghost" onClick={() => setReplacing(true)} className={SECOND}>
                        Replace
                      </Button>
                      <Button variant="ghost" onClick={forget} className={SECOND}>
                        Forget
                      </Button>
                    </div>
                  </>
                )}

                <label htmlFor={`${id}-model`}>Model</label>
                <Input
                  id={`${id}-model`}
                  spellCheck={false}
                  placeholder={suggested}
                  value={draft.model ?? ''}
                  onChange={(e) => edit({ model: e.target.value })}
                  onBlur={() => void save().catch(said)}
                  className={cn(FIELD, 'text-ink')}
                />

                {service === 'custom' && (
                  <>
                    <label htmlFor={`${id}-address`}>Address</label>
                    <Input
                      id={`${id}-address`}
                      spellCheck={false}
                      placeholder="http://localhost:11434/v1"
                      value={draft.baseUrl ?? ''}
                      onChange={(e) => edit({ baseUrl: e.target.value })}
                      onBlur={() => void save().catch(said)}
                      className={cn(FIELD, 'text-ink')}
                    />
                  </>
                )}

                <span aria-hidden />
                {testButton}
              </div>
              {testAnswer}
            </>
          )}
        </Way>
      </div>
      {problem && (
        <p role="alert" className="select-text border-t py-4 text-[13px]">
          {problem}
        </p>
      )}
      <p className="mt-[22px] max-w-[640px] text-[12px] leading-normal text-quiet">
        Test makes one small request, so a key is billed a fraction of a cent. When nothing is
        chosen, Frameflow uses Claude Code if it is on this PC, then OpenCode, then asks for a key.
      </p>
    </Frame>
  )
}

/** The page around its one section: the top bar, the index of sections, the heading and what it is for. */
function Frame({ children }: { children?: React.ReactNode }): React.JSX.Element {
  return (
    <>
      <header className="flex h-[52px] flex-none items-center border-b px-6">
        <h1 className="text-[14px] font-bold">Settings</h1>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav aria-label="Settings" className="w-[260px] flex-none border-r px-6 py-7">
          <p className="mb-3 text-[12px] text-quiet">Settings</p>
          <a
            href="#how-frameflow-thinks"
            aria-current="true"
            className="flex h-8 items-baseline gap-2.5 border-t-2 border-ink pt-2 text-[13px]"
          >
            <b className="text-[12px]">01</b> How Frameflow thinks
          </a>
        </nav>
        <section
          id="how-frameflow-thinks"
          aria-labelledby="how-frameflow-thinks-title"
          className="min-w-0 flex-1 overflow-y-auto px-10 pb-10 pt-7"
        >
          <div className="max-w-[820px]">
            <h2
              id="how-frameflow-thinks-title"
              className="text-[40px] font-bold leading-none tracking-[-0.03em]"
            >
              How Frameflow thinks
            </h2>
            <p className="mb-[22px] mt-1.5 text-[15px] text-quiet">
              Frameflow writes the plan, the storyboard and your changes in words with an agent on
              this PC or with your own API key. Everything it writes is checked before it is used.
            </p>
            {children}
          </div>
        </section>
      </div>
    </>
  )
}

/** One agent in the list: the whole 40 px row chooses it. */
function Agent({
  id,
  name,
  checked,
  disabled,
  onChoose,
  children
}: {
  id: string
  name: string
  checked: boolean
  disabled?: boolean
  onChoose(): void
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <label
      htmlFor={id}
      className={cn(
        'grid h-10 grid-cols-[24px_160px_1fr] items-center border-t text-[13px]',
        disabled ? 'cursor-not-allowed text-faint' : 'cursor-pointer'
      )}
    >
      <input
        id={id}
        type="radio"
        name="agent"
        checked={checked}
        disabled={disabled}
        onChange={onChoose}
        className={cn(RADIO, 'size-4')}
      />
      <span>{name}</span>
      <span className="text-[12px] text-quiet">{children}</span>
    </label>
  )
}
