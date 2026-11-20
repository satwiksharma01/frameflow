import { ExternalLink, Pause, Play } from 'lucide-react'
import { useEffect, useEffectEvent, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { reducedMotion } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { Described } from '@shared/types'
import { LISTEN_AFTER, LISTEN_BEFORE, ScenePlayer } from '../player/ScenePlayer'
import { BuildLine, Steps } from '../storyboard/BuildBar'
import { startBuild, useBuild } from '../storyboard/builds'
import { FiguresLine } from '../storyboard/FiguresLine'
import { actionFor, inTextField } from '../storyboard/keys'
import { clock, toView, type SceneView, type SectionView } from '../storyboard/model'
import { Notice } from '../storyboard/Storyboard'
import { useStoryboard, type StoryboardState } from '../storyboard/useStoryboard'
import { ChangeInWords } from '../words/ChangeInWords'
import { Check, CheckCount } from './Checks'
import { SceneRules } from './SceneRules'

// The frame's width, in its shape: its confirmed size while the window has room, less when not. A 9:16 or
// 1:1 frame leaves Play and the rules on screen (the top bar, the footer and the column's own 148 px take
// 260 px of the height); a 16:9 one leaves the script 628 px, so a row's words keep 260 px beside its
// number, rule, start and length (the rail and the column's padding and border take 113 px of the width).
// The column is the frame, its padding and border: 57 px more.
const SHAPES = {
  '9:16': { width: 'min(360px, (100vh - 260px) * 9 / 16)', ratio: 'aspect-[9/16]' },
  '16:9': { width: 'min(640px, 100vw - 741px)', ratio: 'aspect-video' },
  '1:1': { width: 'min(360px, 100vh - 260px)', ratio: 'aspect-square' }
}

const two = (n: number): string => String(n).padStart(2, '0')

/** A time to the tenth, as the player says it: 0:09.4. */
function tenths(seconds: number): string {
  const t = Math.floor(seconds * 10) / 10
  return `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`
}

/** The frame while there is no picture to play, saying why. */
function Plain({
  said,
  more,
  className
}: {
  said: string
  more?: string
  className: string
}): React.JSX.Element {
  return (
    <div
      role="status"
      className={cn(
        'grid place-items-center overflow-hidden rounded-xl bg-plain p-6 text-center',
        className
      )}
    >
      <div>
        <p className="mx-auto max-w-[280px] break-words text-[15px] leading-[1.35]">{said}</p>
        {more && <p className="mt-2 text-[12px] text-quiet">{more}</p>}
      </div>
    </div>
  )
}

function Heading({ section }: { section: SectionView }): React.JSX.Element {
  const last = section.scenes.at(-1)
  return (
    <h2 className="mb-1 mt-[22px] flex items-baseline gap-2.5 text-[15px] font-bold tracking-[-0.01em]">
      <span className="text-[11px]">{two(section.number)}</span>
      {section.title}
      {section.start !== null && last && last.start !== null && (
        <span className="time ml-auto text-[11px] font-normal text-quiet">
          {clock(section.start)}–{clock(last.start + (last.seconds ?? 0))}
        </span>
      )}
    </h2>
  )
}

interface Props {
  folder: string
  described: Described
  /** Open the storyboard on this scene. */
  onGoTo(scene: number): void
  /** The storyboard the video is read from; with it, the footer has the field to change it in words. */
  state?: StoryboardState
  onSettings?(): void
}

/** The video step: the preview in the video's shape with its scenes' rules as the way through it, the
 *  whole script beside it with the checks, and Open in OpenShot. Until a preview of the storyboard as it
 *  is now is there, the frame says why and the footer offers what comes next. */
export function VideoScreen({
  folder,
  described,
  onGoTo,
  state,
  onSettings
}: Props): React.JSX.Element {
  const build = useBuild(folder)
  const view = useMemo(() => toView(described), [described])
  const scenes = useMemo(() => view.sections.flatMap((s) => s.scenes), [view])
  const report = described.built ? described.report : null
  const building = build.state === 'building'
  const failed = build.state === 'failed'
  // Only a preview of the storyboard as it is now plays, and none while a build replaces it.
  const preview = (report && !building && !failed && described.preview) || null
  const total = view.figures.seconds ?? 0
  const shape = SHAPES[described.aspect ?? '9:16']
  const wide = described.aspect === '16:9'

  const [time, setTime] = useState(0)
  const [stretch, setStretch] = useState<{ from: number; to: number } | null>(null)
  const current = preview
    ? (scenes.findLast((s) => s.start !== null && s.start <= time + 0.001) ?? scenes[0])
    : null

  // On arrival the keys work on the video at once.
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => root.current?.focus(), [])

  // The script follows the scene playing, once per scene rather than at every moment of it.
  const script = useRef<HTMLElement>(null)
  const playing = current?.number
  useEffect(() => {
    script.current
      ?.querySelector(`[data-scene="${playing}"]`)
      ?.scrollIntoView({ block: 'nearest', behavior: reducedMotion() ? 'instant' : 'smooth' })
  }, [playing])

  const play = (from: number, to = total): void => {
    setTime(from)
    setStretch({ from, to })
  }
  const toggle = (): void => {
    if (stretch) setStretch(null)
    else play(time >= total - 0.05 ? 0 : time) // at the end it plays again from the start
  }
  const playScene = (scene: SceneView): void => {
    if (!preview || scene.start === null) return
    // A clicked rule keeps no focus, so Space then plays and pauses rather than pressing it again.
    root.current?.focus({ preventScroll: true })
    play(scene.start)
  }
  const goTo = (scene: SceneView | undefined): void => {
    if (!scene || scene.start === null) return
    if (stretch) play(scene.start)
    else setTime(scene.start)
  }
  const listen = (at: number): void => {
    // Listen keeps no focus either, so Space pauses it and the arrows go on from scene to scene.
    root.current?.focus({ preventScroll: true })
    play(Math.max(0, at - LISTEN_BEFORE), at + LISTEN_AFTER)
  }

  const onKey = useEffectEvent((event: KeyboardEvent) => {
    const action = actionFor(event, inTextField(event.target))
    if (!current || (action !== 'play' && action !== 'next' && action !== 'previous')) return
    // Space on a button presses it; held down, it would play and pause at the key's repeat.
    const onButton = event.target instanceof Element && event.target.closest('button')
    if (action === 'play' && (event.repeat || onButton)) return
    event.preventDefault()
    if (action === 'play') toggle()
    else goTo(scenes[current.number - 1 + (action === 'next' ? 1 : -1)])
  })
  useEffect(() => {
    const listener = (event: KeyboardEvent): void => onKey(event)
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [])

  // While Open runs, its steps; once it has failed, only what the engine said, in ink.
  const [opening, setOpening] = useState<string[] | null>(null)
  const [notOpened, setNotOpened] = useState<string | null>(null)
  const open = (): void => {
    setOpening([])
    setNotOpened(null)
    let ok = false
    let said = ''
    window.frameflow
      .open(folder, (event) => {
        if (event.type === 'step') setOpening((steps) => steps && [...steps, event.text])
        else if (event.type === 'done') {
          ok = event.ok
          said = event.message ?? ''
        }
      })
      .catch((e: Error) => {
        said = e.message
      })
      .then(() => {
        setOpening(null)
        if (!ok) setNotOpened(said || 'Opening it stopped without saying why.')
      })
  }

  // Built, with no picture on its way: Build video is the main action, and Open in OpenShot sits beside it.
  const offerOpen = !!report && !building && !failed
  const offerBuild = !offerOpen || (!preview && build.state !== 'previewing')
  const skipped = report && typeof report.preview === 'object' ? report.preview.skipped : null

  const frameClass = cn('flex-none rounded-xl w-(--frame)', shape.ratio)
  const frame = preview ? (
    <ScenePlayer
      src={preview}
      from={stretch?.from ?? time}
      to={stretch?.to ?? total}
      paused={!stretch}
      run={stretch ?? undefined}
      onTime={setTime}
      onEnd={() => setStretch(null)}
      className={cn('block', frameClass)}
    />
  ) : building ? (
    <Plain
      className={frameClass}
      said="Building…"
      more="You can leave; you will be told when it is done."
    />
  ) : failed ? (
    <Plain
      className={frameClass}
      said="The build did not finish."
      more="What the engine said is below. Fix it on the storyboard, then build again."
    />
  ) : !report ? (
    <Plain
      className={frameClass}
      said={
        described.ever_built === false
          ? 'This video has not been built yet.'
          : 'The storyboard has changed since this video was built.'
      }
      more="Build it to watch it as it is now."
    />
  ) : build.state === 'previewing' ? (
    <Plain
      className={frameClass}
      said="Making the preview…"
      more="The checks are ready. The picture comes as soon as it is made."
    />
  ) : (
    <Plain
      className={frameClass}
      said={
        skipped ? `The preview was not made: ${skipped}` : 'Build the video to play its scenes.'
      }
    />
  )

  const seconds = view.figures.seconds
  return (
    <div
      ref={root}
      tabIndex={-1}
      style={{ '--frame': shape.width } as React.CSSProperties}
      className="flex min-h-0 flex-1 flex-col outline-none"
    >
      <div className="flex min-h-0 flex-1">
        <section
          aria-label="The video"
          className="w-[calc(var(--frame)_+_57px)] flex-none overflow-y-auto overflow-x-hidden border-r px-7 pb-6 pt-6"
        >
          {frame}
          <div className="mt-3.5 flex items-center gap-3.5 text-[13px] text-quiet">
            <Button
              type="button"
              variant="ghost"
              size="icon-lg"
              aria-label={stretch ? 'Pause' : 'Play'}
              disabled={!preview}
              onClick={toggle}
              className="rounded-lg border border-ink disabled:border-dim disabled:text-faint disabled:opacity-100"
            >
              {stretch ? (
                <Pause aria-hidden fill="currentColor" />
              ) : (
                <Play aria-hidden fill="currentColor" />
              )}
            </Button>
            <span className="time">
              {current ? (
                <>
                  <b className="font-medium text-ink">{tenths(time)}</b> scene {two(current.number)}
                </>
              ) : (
                '0:00'
              )}
            </span>
            <span className="time ml-auto">
              {report ? tenths(total) : seconds !== null ? `about ${clock(seconds)}` : null}
            </span>
          </div>
          <SceneRules
            scenes={scenes}
            current={current}
            at={
              current?.start != null && current.seconds
                ? Math.min(Math.max((time - current.start) / current.seconds, 0), 1)
                : 0
            }
            onJump={playScene}
          />
        </section>
        <section
          ref={script}
          aria-label="Script"
          className="min-w-0 flex-1 overflow-y-auto px-7 pb-10 pt-[22px]"
        >
          <div className="flex items-baseline">
            <FiguresLine figures={view.figures} />
            {report && <CheckCount count={scenes.reduce((sum, s) => sum + s.checks.length, 0)} />}
          </div>
          {view.sections.map((section) => (
            <section key={section.number} className={cn(section.title === null && 'mt-3')}>
              {section.title !== null && <Heading section={section} />}
              <ol>
                {section.scenes.map((scene) => {
                  const now = scene.number === current?.number
                  return (
                    <li
                      key={scene.key}
                      data-scene={scene.number}
                      aria-current={now || undefined}
                      onClick={(e) => {
                        if (!(e.target as Element).closest('button')) playScene(scene)
                      }}
                      className={cn(
                        'grid grid-cols-[30px_132px_44px_1fr_48px] items-baseline gap-x-3 border-t pb-2.5 pt-[9px] text-[12px] text-quiet',
                        now && 'border-t-2 border-t-ink'
                      )}
                    >
                      <b className="text-[15px] font-bold text-ink">{two(scene.number)}</b>
                      {/* A line of the words' size, so the rule sits on their first line in a tall row. */}
                      <span className="text-[15px] leading-[1.3]">
                        {scene.seconds !== null && (
                          <span
                            data-track
                            style={{ width: scene.rule * 132 }}
                            className={cn(
                              'inline-block h-[3px] min-w-1 rounded-[2px] align-middle',
                              now ? 'bg-signal' : 'bg-ink'
                            )}
                          />
                        )}
                      </span>
                      <span className="time">
                        {scene.start === null ? '–' : clock(scene.start)}
                      </span>
                      <p
                        className={cn(
                          'text-[15px] leading-[1.3] text-ink first-letter:uppercase',
                          wide && 'line-clamp-2'
                        )}
                      >
                        {scene.says}
                      </p>
                      <span className="time text-right">
                        {scene.seconds !== null && `${scene.seconds.toFixed(1)} s`}
                      </span>
                      {scene.checks.map((check, i) => (
                        <Check
                          key={i}
                          check={check.what}
                          canListen={!!preview}
                          onListen={() => listen(check.at)}
                          onGoTo={() => onGoTo(scene.number)}
                        />
                      ))}
                    </li>
                  )
                })}
              </ol>
            </section>
          ))}
        </section>
      </div>
      <footer className="relative flex h-[60px] flex-none items-center gap-5 border-t px-6">
        {failed && (
          <div
            role="alert"
            // Over the script column, from its words to the footer's right edge.
            className="absolute bottom-full left-[calc(var(--frame)_+_85px)] right-6 mb-3 max-h-48 select-text overflow-y-auto whitespace-pre-wrap rounded-xl border border-dim bg-ground px-4 py-3 text-[13px] text-signal-ink"
          >
            {build.message}
          </div>
        )}
        {offerOpen && notOpened && (
          <div
            role="alert"
            className="absolute bottom-full right-6 mb-3 w-[560px] select-text whitespace-pre-wrap rounded-xl border border-dim bg-ground px-4 py-3 text-[13px] text-ink"
          >
            {notOpened}
          </div>
        )}
        <BuildLine build={build} described={described} />
        {offerOpen ? (
          <Steps label="Opening steps" steps={opening ?? []} running failed={false} />
        ) : (
          <Steps label="Build steps" steps={build.steps} running={building} failed={failed} />
        )}
        {state && (
          <ChangeInWords
            folder={folder}
            state={state}
            onDone={() => root.current?.focus()}
            onSettings={onSettings}
          />
        )}
        {offerOpen && (
          <Button
            onClick={open}
            disabled={opening !== null}
            variant={offerBuild ? 'ghost' : 'default'}
            className={cn(
              'h-10 flex-none gap-2.5 rounded-lg px-[22px] text-[13px] font-bold',
              offerBuild && 'border border-dim'
            )}
          >
            <ExternalLink aria-hidden />
            Open in OpenShot
          </Button>
        )}
        {offerBuild && (
          <Button
            onClick={() => {
              setNotOpened(null) // about the build before this one
              startBuild(folder)
            }}
            disabled={building}
            className="h-10 flex-none rounded-lg px-[22px] text-[13px] font-bold"
          >
            {building ? 'Building…' : 'Build video'}
          </Button>
        )}
      </footer>
    </div>
  )
}

/** The video as the engine describes it, read again when a build of it lands, on the video screen. */
export function VideoStep({
  folder,
  onGoTo,
  onSettings
}: {
  folder: string
  onGoTo(scene: number): void
  onSettings?(): void
}): React.JSX.Element | null {
  const state = useStoryboard(folder)
  const built = useBuild(folder).built
  const seen = useRef(built)
  useEffect(() => {
    if (built > seen.current) state.reload()
    seen.current = built
  }, [built, state])

  if (state.status === 'failed') {
    return (
      <Notice title="Frameflow could not read this video">
        <p role="alert" className="mt-2 select-text whitespace-pre-wrap text-signal-ink">
          {state.message}
        </p>
      </Notice>
    )
  }
  if (state.described?.no_storyboard) return null // its prompt step is shown instead
  if (!state.described)
    return <div aria-busy="true" aria-label="Loading the video" className="flex-1" />
  return (
    <VideoScreen
      folder={folder}
      described={state.described}
      onGoTo={onGoTo}
      state={state}
      onSettings={onSettings}
    />
  )
}
