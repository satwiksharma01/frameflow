import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { BuildEvent, Described, Video } from '@shared/types'
import App from '../App'
import { startBuild } from '../storyboard/builds'
import { longVideo, tierList, twoCuts, unbuilt } from '../storyboard/fixture'
import { summary } from '../storyboard/model'
import { VideoScreen, VideoStep } from './VideoScreen'

const FOLDER = 'E:\\my projects\\frameflow\\output\\reference-swap'
const PREVIEW = 'ff-media://preview/?p=x'
const built: Described = { ...tierList, preview: PREVIEW }

const video = (): HTMLVideoElement | null => document.querySelector('video')
function at(seconds: number): void {
  video()!.currentTime = seconds
  fireEvent.timeUpdate(video()!)
}
const row = (n: number): HTMLElement => document.querySelector<HTMLElement>(`[data-scene="${n}"]`)!
const rule = (n: number): HTMLElement => screen.getByRole('button', { name: `Scene ${n}` })
const button = (name: string): HTMLElement => screen.getByRole('button', { name })
const steps = (name: string): (string | null)[][] =>
  within(screen.getByRole('list', { name }))
    .getAllByRole('listitem')
    .map((s) => [s.textContent, s.getAttribute('data-state')])

function show(
  described: Described = built,
  engine: object = {}
): { onGoTo: ReturnType<typeof vi.fn> } {
  window.frameflow = { thumbnail: async () => null, ...engine } as never
  const onGoTo = vi.fn()
  render(<VideoScreen folder={FOLDER} described={described} onGoTo={onGoTo} />)
  return { onGoTo }
}

/** A build the test drives: `say` sends what the engine prints, `end` finishes it. */
function fakeBuild(): {
  build: ReturnType<typeof vi.fn>
  say: (...events: BuildEvent[]) => void
  end: (ok?: boolean, message?: string) => Promise<void>
} {
  let onEvent: (e: BuildEvent) => void = () => {}
  let finish: () => void = () => {}
  const build = vi.fn((_folder: string, listener: (e: BuildEvent) => void) => {
    onEvent = listener
    return new Promise<void>((resolve) => (finish = resolve))
  })
  return {
    build,
    say: (...events) => act(() => events.forEach((e) => onEvent(e))),
    end: async (ok = true, message) => {
      await act(async () => {
        onEvent(ok ? { type: 'done', ok } : { type: 'done', ok, message })
        finish()
      })
    }
  }
}

it('a built video shows its preview and one rule per scene, each as wide as the scene is long', () => {
  show()
  expect(video()).toHaveAttribute('src', PREVIEW)
  expect(video()!.paused).toBe(true)
  const rules = within(screen.getByRole('group', { name: 'Scenes' })).getAllByRole('button')
  expect(rules).toHaveLength(9)
  expect(rules.map((r) => Number(r.style.flexGrow))).toEqual(tierList.scenes.map((s) => s.seconds))
  expect(screen.getByText('0:00.0').parentElement).toHaveTextContent('0:00.0 scene 01')
  expect(screen.getByText('0:20.1')).toBeInTheDocument()
})

it("clicking a scene's rule plays from that scene's start", async () => {
  show()
  await userEvent.click(rule(6))
  expect(video()!.currentTime).toBe(8.7)
  expect(video()!.paused).toBe(false)
  at(9.4)
  expect(screen.getByText('0:09.4').parentElement).toHaveTextContent('0:09.4 scene 06')
  expect(rule(5)).toHaveAttribute('data-rule', 'played')
  expect(rule(6)).toHaveAttribute('data-rule', 'current')
  expect(rule(7)).toHaveAttribute('data-rule', 'ahead')
  expect(row(6)).toHaveAttribute('aria-current', 'true')
  await userEvent.click(rule(6)) // again: back to its start
  expect(video()!.currentTime).toBe(8.7)
})

it('Space pauses after a rule click, and plays on again', async () => {
  show()
  await userEvent.click(rule(6))
  expect(video()!.paused).toBe(false)
  at(9.4)
  await userEvent.keyboard(' ')
  expect(video()!.paused).toBe(true)
  await userEvent.keyboard(' ')
  expect(video()!.paused).toBe(false)
  expect(video()!.currentTime).toBe(9.4)
})

it('a click on a row plays from its start', async () => {
  show()
  await userEvent.click(within(row(8)).getByText('already almost finished'))
  expect(video()!.currentTime).toBe(16.233)
  expect(video()!.paused).toBe(false)
})

it('Space plays and pauses, and the arrows jump to the previous and next scene', async () => {
  show()
  await userEvent.keyboard(' ')
  expect(video()!.paused).toBe(false)
  expect(button('Pause')).toBeInTheDocument()
  at(2)
  await userEvent.keyboard(' ')
  expect(video()!.paused).toBe(true)
  expect(button('Play')).toBeInTheDocument()
  await userEvent.keyboard('{ArrowRight}')
  expect(video()!.currentTime).toBe(3.267)
  expect(video()!.paused).toBe(true)
  await userEvent.keyboard('{ArrowLeft}{ArrowLeft}')
  expect(video()!.currentTime).toBe(0)
  await userEvent.keyboard(' {ArrowRight}')
  expect(video()!.currentTime).toBe(1.467) // playing, it plays on from there
  expect(video()!.paused).toBe(false)
})

it('each check is listed with its time, and Listen plays around it', async () => {
  show()
  expect(row(6)).toHaveTextContent('0:08')
  expect(within(row(6)).getByText('May clip “work”')).toBeInTheDocument()
  expect(screen.getAllByText(/May clip/)).toHaveLength(1)
  const listen = within(row(6)).getByRole('button', { name: 'Listen' })
  await userEvent.click(listen)
  expect(video()!.currentTime).toBeCloseTo(9.933)
  expect(video()!.paused).toBe(false)
  at(12.4)
  expect(video()!.paused).toBe(false)
  at(12.433)
  expect(video()!.paused).toBe(true)
  expect(listen).not.toHaveFocus() // the keys play and pause the video again
  await userEvent.keyboard(' ')
  expect(video()!.paused).toBe(false)
  expect(video()!.currentTime).toBeCloseTo(12.433)
})

it('a scene with two suspect cuts lists both, each with a Listen around its own moment, and counts both', async () => {
  show({ ...twoCuts, preview: PREVIEW })
  expect(within(row(6)).getByText('May clip “all”')).toBeInTheDocument()
  expect(within(row(6)).getByText('May clip “work”')).toBeInTheDocument()
  const listens = within(row(6)).getAllByRole('button', { name: 'Listen' })
  expect(listens).toHaveLength(2)
  await userEvent.click(listens[0])
  expect(video()!.currentTime).toBeCloseTo(8.5)
  at(10.967)
  expect(video()!.paused).toBe(false)
  at(11.0)
  expect(video()!.paused).toBe(true)
  await userEvent.click(listens[1])
  expect(video()!.currentTime).toBeCloseTo(9.933)
  at(12.433)
  expect(video()!.paused).toBe(true)
  // The script and the footer count the same checks.
  expect(screen.getByText('2 to check')).toBeInTheDocument()
  expect(screen.getByText(summary(twoCuts))).toHaveTextContent('2 to listen to')
})

describe('a long video', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('numbers under its rules never touch: in a 248 px strip, scene 12 playing shows 01, 12 and 22', async () => {
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(private told: ResizeObserverCallback) {}
        observe(): void {
          this.told([{ contentRect: { width: 248 } }] as never, this as never)
        }
        disconnect(): void {
          // nothing to stop: it reported once
        }
      }
    )
    show({ ...longVideo, preview: PREVIEW })
    await userEvent.click(rule(12))
    const numbers = longVideo.scenes.map((s) => rule(s.number).textContent)
    expect(numbers.filter(Boolean)).toEqual(['01', '12', '22'])
  })

  it('the playing row scrolls into view when the scene changes, and not as it plays on within one', async () => {
    const scrolled: [Element, ScrollIntoViewOptions][] = []
    Element.prototype.scrollIntoView = function (this: Element, options) {
      scrolled.push([this, options as ScrollIntoViewOptions])
    }
    show({ ...longVideo, preview: PREVIEW })
    scrolled.length = 0
    await userEvent.click(rule(12)) // a rule
    expect(scrolled).toEqual([[row(12), { block: 'nearest', behavior: 'smooth' }]])
    at(12 * 27 - 1) // playing on in scene 12
    expect(scrolled).toHaveLength(1)
    at(12 * 27 + 1) // into scene 13
    expect(scrolled.map(([element]) => element)).toEqual([row(12), row(13)])
    await userEvent.keyboard('{ArrowRight}') // the arrows
    expect(scrolled.map(([element]) => element)).toEqual([row(12), row(13), row(14)])
  })

  it('with less motion, the playing row comes into view at once', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce') }))
    const scrolled = vi.fn()
    Element.prototype.scrollIntoView = scrolled
    show({ ...longVideo, preview: PREVIEW })
    await userEvent.click(rule(12))
    expect(scrolled).toHaveBeenLastCalledWith({ block: 'nearest', behavior: 'instant' })
  })
})

it("a tall row's rule sits on its first line, not in the middle of the row", () => {
  show()
  // jsdom lays nothing out: the rule is drawn in a line of the words' size, centred on it as a dash is.
  const track = row(7).querySelector<HTMLElement>('[data-track]')!
  expect(track).toHaveClass('inline-block', 'align-middle')
  expect(track.parentElement).toHaveClass('text-[15px]', 'leading-[1.3]')
  expect(track.parentElement).not.toHaveClass('self-center')
})

it('Go to scene 06 opens the storyboard with scene 6 selected', async () => {
  const reel: Video = {
    folder: FOLDER,
    title: 'Editing tier list',
    has_storyboard: true,
    built: true,
    cover: 'scene-1'
  }
  window.frameflow = {
    videos: async () => [reel],
    describe: async () => built,
    thumbnail: async () => null,
    looks: async () => []
  } as never
  render(<App />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.click(button('Video'))
  await userEvent.click(await screen.findByRole('button', { name: 'Open in the storyboard' }))
  const six = await screen.findByRole('button', { name: /^Scene 6:/ })
  expect(six).toHaveAttribute('aria-current', 'true')
  await waitFor(() => expect(six).toHaveFocus())
  expect(button('Storyboard')).toHaveAttribute('aria-current', 'step')
})

it('a video changed since its build says so and offers Build video', async () => {
  const { build } = fakeBuild()
  show({ ...unbuilt, ever_built: true }, { build })
  expect(screen.getByRole('status')).toHaveTextContent(
    'The storyboard has changed since this video was built.Build it to watch it as it is now.'
  )
  expect(video()).toBeNull()
  expect(button('Play')).toBeDisabled()
  expect(rule(1)).toBeDisabled()
  expect(screen.getByRole('group', { name: 'Length' })).toHaveTextContent('about 20.1/20 seconds')
  expect(screen.getByText('about 0:20')).toBeInTheDocument()
  expect(row(6)).toHaveTextContent('–')
  expect(row(6)).not.toHaveTextContent('0:08')
  expect(screen.queryByText(/May clip|to check/)).toBeNull()
  expect(screen.getByText('Not built since it last changed.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Open in OpenShot' })).toBeNull()
  await userEvent.click(button('Build video'))
  expect(build).toHaveBeenCalledWith(FOLDER, expect.any(Function))
})

it('a video never built says so in the frame and the footer, and offers Build video', () => {
  show({ ...unbuilt, ever_built: false })
  expect(screen.getByRole('status')).toHaveTextContent(
    'This video has not been built yet.Build it to watch it as it is now.'
  )
  expect(screen.getByText('Not built yet.')).toBeInTheDocument()
  expect(screen.queryByText('Not built since it last changed.')).toBeNull()
  expect(button('Build video')).toBeEnabled()
})

it('while the preview is being made the screen says so and already lists the checks', () => {
  window.frameflow = {
    build: vi.fn((_folder: string, onEvent: (e: BuildEvent) => void) => {
      onEvent({ type: 'built' })
      return new Promise<void>(() => {})
    })
  } as never
  startBuild(FOLDER)
  render(<VideoScreen folder={FOLDER} described={tierList} onGoTo={() => {}} />)
  expect(screen.getByRole('status')).toHaveTextContent(
    'Making the preview…The checks are ready. The picture comes as soon as it is made.'
  )
  expect(video()).toBeNull()
  expect(button('Play')).toBeDisabled()
  expect(rule(6)).toBeDisabled()
  expect(rule(6)).toHaveAttribute('data-rule', 'ahead')
  // Off, as the sketch draws it: the confirmed grey, not a faded control.
  expect(rule(6).querySelector('[data-bar]')).toHaveClass('bg-dim')
  expect(button('Play')).toHaveClass('disabled:border-dim', 'disabled:opacity-100')
  expect(within(row(6)).getByText('May clip “work”')).toBeInTheDocument()
  expect(within(row(6)).getByRole('button', { name: 'Listen' })).toBeDisabled()
  expect(within(row(6)).getByRole('button', { name: 'Listen' })).toHaveClass('disabled:border-dim')
  expect(screen.getByText('1 to check')).toBeInTheDocument()
  expect(screen.getByText(`${summary(tierList)} Making the preview…`)).toBeInTheDocument()
  expect(button('Open in OpenShot')).toBeEnabled()
})

it('Open in OpenShot starts opening it and shows its step; a failure says why and stays', async () => {
  let onEvent: (e: BuildEvent) => void = () => {}
  let finish: () => void = () => {}
  const open = vi.fn((_folder: string, listener: (e: BuildEvent) => void) => {
    onEvent = listener
    return new Promise<void>((resolve) => (finish = resolve))
  })
  show(built, { open })
  await userEvent.click(button('Open in OpenShot'))
  expect(open).toHaveBeenCalledWith(FOLDER, expect.any(Function))
  expect(button('Open in OpenShot')).toBeDisabled()
  act(() => onEvent({ type: 'step', text: 'Opening it in OpenShot' }))
  expect(steps('Opening steps')).toEqual([['Opening it in OpenShot', 'current']])
  const said =
    'OpenShot was not found. Open E:\\my projects\\frameflow\\output\\reference-swap\\Editing-tier-list.osp yourself.'
  await act(async () => {
    onEvent({ type: 'done', ok: false, message: said })
    finish()
  })
  expect(screen.getByRole('alert')).toHaveTextContent(said)
  expect(screen.getByRole('alert')).toHaveClass('text-ink', 'border-dim')
  // Only the note, in ink: no crossed step in red.
  expect(screen.queryByRole('list', { name: 'Opening steps' })).toBeNull()
  expect(screen.getByRole('contentinfo').querySelectorAll('.text-signal-ink')).toHaveLength(0)
  expect(button('Open in OpenShot')).toBeEnabled()
  await userEvent.click(rule(6)) // the screen stays as built, and what it said stays
  expect(video()!.paused).toBe(false)
  expect(screen.getByRole('alert')).toHaveTextContent(said)
})

it('Space during a Listen pauses it rather than starting it again', async () => {
  show()
  await userEvent.click(within(row(6)).getByRole('button', { name: 'Listen' }))
  at(10.5)
  await userEvent.keyboard(' ')
  expect(video()!.paused).toBe(true)
  expect(video()!.currentTime).toBe(10.5)
  await userEvent.keyboard('{ArrowRight}') // and the arrows go on from scene to scene
  expect(video()!.currentTime).toBe(11.433)
})

it('what a failed Open said goes once a build starts, and is never a second alert', async () => {
  let onOpen: (e: BuildEvent) => void = () => {}
  let opened: () => void = () => {}
  const open = vi.fn((_folder: string, listener: (e: BuildEvent) => void) => {
    onOpen = listener
    return new Promise<void>((resolve) => (opened = resolve))
  })
  const { build, end } = fakeBuild()
  show({ ...tierList, preview: null }, { open, build })
  await userEvent.click(button('Open in OpenShot'))
  await act(async () => {
    onOpen({ type: 'done', ok: false, message: 'OpenShot was not found. Open x.osp yourself.' })
    opened()
  })
  expect(screen.getByRole('alert')).toHaveTextContent('OpenShot was not found')
  await userEvent.click(button('Build video'))
  expect(screen.queryByRole('alert')).toBeNull()
  await end(false, 'the storyboard needs fixing')
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect(screen.getByRole('alert')).toHaveTextContent('the storyboard needs fixing')
})

it('an Open that works leaves the footer as it was', async () => {
  const open = vi.fn(async (_folder: string, onEvent: (e: BuildEvent) => void) => {
    onEvent({ type: 'step', text: 'Opening it in OpenShot' })
    onEvent({ type: 'done', ok: true })
  })
  show(built, { open })
  await userEvent.click(button('Open in OpenShot'))
  await waitFor(() => expect(button('Open in OpenShot')).toBeEnabled())
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.queryByRole('list', { name: 'Opening steps' })).toBeNull()
  expect(screen.getByText(summary(tierList))).toBeInTheDocument()
})

describe('the confirmed states and sizes', () => {
  it('Built and current: the figures with "1 to check" in red, chapters with their spans, a row per scene', () => {
    show()
    expect(screen.getByRole('group', { name: 'Length' })).toHaveTextContent('20.1/20 seconds')
    expect(screen.getByText('1 to check')).toHaveClass('text-signal-ink')
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
      '01Problem0:00–0:08',
      '02Turn0:08–0:11',
      '03Answer0:11–0:20'
    ])
    expect(row(7)).toHaveTextContent(/^070:11create a complete first cut.*4\.8 s$/)
    // Each row's rule in a 132 px track, scaled to the longest scene (7, 4.8 s).
    expect(row(7).querySelector<HTMLElement>('[data-track]')).toHaveStyle({ width: '132px' })
    expect(row(3).querySelector<HTMLElement>('[data-track]')).toHaveStyle({ width: '33px' })
  })

  it('red keeps its jobs: the current scene’s rules and the check’s wording', () => {
    show()
    expect(row(1)).toHaveAttribute('aria-current', 'true')
    expect([...document.querySelectorAll('.bg-signal')]).toEqual([
      rule(1).querySelector('[data-bar]'),
      row(1).querySelector('[data-track]')
    ])
    expect([...document.querySelectorAll('.text-signal-ink')].map((e) => e.textContent)).toEqual([
      '1 to check',
      expect.stringContaining('May clip “work”')
    ])
  })

  it('"Nothing to check" in grey when the build found nothing', () => {
    show({ ...built, report: { ...tierList.report!, joins: { checked: 8, suspect: [] } } })
    expect(screen.getByText('Nothing to check')).toHaveClass('text-quiet')
    expect(screen.queryByRole('button', { name: 'Listen' })).toBeNull()
  })

  it('Building: the frame says so, and the footer shows Build’s steps with its button "Building…", off', async () => {
    const { build, say } = fakeBuild()
    show(unbuilt, { build })
    await userEvent.click(button('Build video'))
    say(
      { type: 'step', text: 'Recording the voiceover' },
      { type: 'step', text: 'Listening to every cut' },
      { type: 'detail', text: 'Checking cut 5 of 8' }
    )
    expect(screen.getByRole('status')).toHaveTextContent(
      'Building…You can leave; you will be told when it is done.'
    )
    expect(steps('Build steps')).toEqual([
      ['Recording the voiceover', 'done'],
      ['Listening to every cut', 'current']
    ])
    expect(screen.getByText('Checking cut 5 of 8')).toBeInTheDocument()
    expect(button('Building…')).toBeDisabled()
    expect(button('Play')).toBeDisabled()
  })

  it('while it builds, Stop beside Building… stops it', async () => {
    const { build, say } = fakeBuild()
    const stop = vi.fn(async () => true)
    show(unbuilt, { build, stop })
    await userEvent.click(button('Build video'))
    say({ type: 'step', text: 'Recording the voiceover' })
    await userEvent.click(button('Stop the build'))
    expect(stop).toHaveBeenCalledWith('build', FOLDER)
  })

  it('A failed build: the engine’s words over the script, the failed step marked, and Build video', async () => {
    const { build, say, end } = fakeBuild()
    show(unbuilt, { build })
    await userEvent.click(button('Build video'))
    say(
      { type: 'step', text: 'Recording the voiceover' },
      { type: 'step', text: 'Preparing the pictures' }
    )
    await end(false, "the storyboard needs fixing:\n  'two' is not said in scene 9")
    expect(screen.getByRole('alert')).toHaveTextContent("'two' is not said in scene 9")
    expect(screen.getByRole('alert')).toHaveClass(
      'text-signal-ink',
      'border-dim',
      'left-[calc(var(--frame)_+_85px)]' // over the script column, at its words
    )
    expect(screen.getByRole('status')).toHaveTextContent(
      'The build did not finish.What the engine said is below. Fix it on the storyboard, then build again.'
    )
    expect(
      within(screen.getByRole('contentinfo')).getByText('The build did not finish.')
    ).toBeInTheDocument()
    expect(steps('Build steps')).toEqual([
      ['Recording the voiceover', 'done'],
      ['Preparing the pictures', 'failed']
    ])
    expect(button('Build video')).toBeEnabled()
  })

  it('a build with no preview offers Build video, Open in OpenShot beside it, and says to build to play', async () => {
    const { build } = fakeBuild()
    show({ ...tierList, preview: null }, { build })
    expect(video()).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('Build the video to play its scenes.')
    expect(button('Play')).toBeDisabled()
    const actions = within(screen.getByRole('contentinfo')).getAllByRole('button')
    expect(actions.map((b) => b.textContent)).toEqual(['Open in OpenShot', 'Build video'])
    expect(button('Open in OpenShot')).toHaveClass('h-10', 'border-dim') // the second button
    expect(button('Open in OpenShot')).toBeEnabled()
    await userEvent.click(button('Build video'))
    expect(build).toHaveBeenCalledWith(FOLDER, expect.any(Function))
  })

  it('a build whose preview was skipped says why there is no picture', () => {
    const report = { ...tierList.report!, preview: { skipped: 'OpenShot is not installed' } }
    show({ ...tierList, report, preview: null })
    expect(screen.getByRole('status')).toHaveTextContent(
      'The preview was not made: OpenShot is not installed'
    )
    expect(button('Build video')).toBeEnabled()
  })

  // The frame keeps its confirmed size while the window has room for it, and shrinks in its shape when
  // not; the column is the frame and its padding, so nothing ever scrolls sideways.
  const frame = (): string =>
    screen
      .getByRole('region', { name: 'The video' })
      .closest<HTMLElement>('[tabindex="-1"]')!
      .style.getPropertyValue('--frame')

  it('9:16: 360 px wide, or less to keep Play and the rules on screen; the 16 px corner', () => {
    show()
    expect(frame()).toBe('min(360px, (100vh - 260px) * 9 / 16)')
    expect(video()).toHaveClass('w-(--frame)', 'aspect-[9/16]', 'rounded-xl', 'block')
    expect(screen.getByRole('region', { name: 'The video' })).toHaveClass(
      'w-[calc(var(--frame)_+_57px)]',
      'overflow-x-hidden'
    )
  })

  it('16:9: 640 px wide, or less to leave the script 628 px; its words at most two lines', () => {
    show({ ...built, aspect: '16:9' })
    expect(frame()).toBe('min(640px, 100vw - 741px)') // the script keeps 628 px, its words 260
    expect(video()).toHaveClass('w-(--frame)', 'aspect-video', 'rounded-xl')
    expect(within(row(7)).getByText(/create a complete/)).toHaveClass('line-clamp-2')
  })

  it('1:1: 360 px square, or less to keep Play and the rules on screen', () => {
    show({ ...built, aspect: '1:1' })
    expect(frame()).toBe('min(360px, 100vh - 260px)')
    expect(video()).toHaveClass('w-(--frame)', 'aspect-square')
  })

  it('a frame with no picture keeps the same shape and size', () => {
    show(unbuilt)
    expect(screen.getByRole('status')).toHaveClass('w-(--frame)', 'aspect-[9/16]', 'rounded-xl')
  })

  it('every control is at least 32 px, and Open in OpenShot, the main action, is 40 px', () => {
    show()
    expect(button('Play')).toHaveClass('size-10')
    expect(button('Open in OpenShot')).toHaveClass('h-10')
    expect(rule(1)).toHaveClass('h-8')
    expect(within(row(6)).getByRole('button', { name: 'Listen' })).toHaveClass('h-8')
    expect(within(row(6)).getByRole('button', { name: 'Open in the storyboard' })).toHaveClass(
      'h-8'
    )
  })
})

it('the video step reads the video again when a build of it lands, and shows its checks', async () => {
  const { build, say } = fakeBuild()
  const describe = vi.fn().mockResolvedValueOnce(unbuilt).mockResolvedValue(tierList)
  window.frameflow = { describe, build, thumbnail: async () => null } as never
  render(<VideoStep folder={FOLDER} onGoTo={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Build video' }))
  say({ type: 'step', text: 'Listening to every cut' }, { type: 'built' })
  expect(await screen.findByText('May clip “work”')).toBeInTheDocument()
  expect(describe).toHaveBeenCalledTimes(2)
})

it('the video step of a video without a storyboard shows nothing: the prompt step writes one', async () => {
  const describe = vi.fn(async () => ({
    title: 'Morning routine',
    scenes: [],
    no_storyboard: true
  }))
  window.frameflow = { describe, thumbnail: async () => null } as never
  const { container } = render(<VideoStep folder={FOLDER} onGoTo={() => {}} />)
  await waitFor(() => expect(describe).toHaveBeenCalled())
  await waitFor(() => expect(screen.queryByLabelText('Loading the video')).toBeNull())
  expect(screen.queryByText('No storyboard yet')).toBeNull()
  expect(container).toBeEmptyDOMElement()
})
