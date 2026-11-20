import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { reducedMotion, springEasing } from '@/lib/motion'
import type { ThinkRequest, Video } from '@shared/types'
import { PromptStep } from './prompt/PromptStep'
import type { Done } from './prompt/thinking'
import { SettingsPage } from './settings/SettingsPage'
import { say, Toasts } from './shell/Toasts'
import { TopBar, type Step } from './shell/TopBar'
import { VideoRail } from './shell/VideoRail'
import { BuildBar } from './storyboard/BuildBar'
import { Storyboard } from './storyboard/Storyboard'
import { VideoSettings } from './storyboard/VideoSettings'
import { VideoStep } from './video/VideoScreen'

const EASING = springEasing()
const ORDER: Step[] = ['prompt', 'storyboard', 'video']

function App(): React.JSX.Element {
  const [videos, setVideos] = useState<Video[] | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [folder, setFolder] = useState<string | null>(null)
  const [steps, setSteps] = useState<Record<string, Step>>({})
  const [settings, setSettings] = useState(false) // a page of its own, with or without a video
  const [creating, setCreating] = useState(false) // New video: the prompt, with no folder until it is asked
  // The new videos' folders. The engine lists a video once its material is prepared, which can take minutes.
  const [made, setMade] = useState<string[]>([])
  const [revision, setRevision] = useState(0) // rises when the storyboard is put back from outside it
  // The scene the storyboard opens on when the creator comes back to it from the video: the one they
  // left it on, or the one a check sent them to. Another video opens on its first scene.
  const [scene, setScene] = useState<number>()
  const selected = useRef(1)
  const screen = useRef<HTMLDivElement>(null)
  const moving = useRef(0) // 1: the next step comes in from the right; -1: the one before, from the left

  const listed: Video[] = [
    ...made
      .filter((f) => !videos?.some((v) => v.folder === f))
      .map((f) => ({
        folder: f,
        title: f.split(/[\\/]/).pop() ?? f, // as the engine names a video with no plan yet
        has_storyboard: false,
        built: false,
        cover: null
      })),
    ...(videos ?? [])
  ]
  const video = listed.find((v) => v.folder === folder)
  const ready = !!video?.has_storyboard // the storyboard and the video wait for an approved plan
  const step: Step = ready ? (folder && steps[folder]) || 'storyboard' : 'prompt'
  const go = (next: Step, at = selected.current): void => {
    if (!folder || next === step) return
    moving.current = ORDER.indexOf(next) > ORDER.indexOf(step) ? 1 : -1
    setScene(at)
    setSteps((s) => ({ ...s, [folder]: next }))
  }
  const open = (next: string): void => {
    setSettings(false)
    setCreating(false)
    setFolder(next)
    setScene(undefined)
    selected.current = 1
  }

  // A step slides in from its side of the step bar; with less motion it fades in.
  useLayoutEffect(() => {
    const way = moving.current
    moving.current = 0
    if (!way) return
    const reduce = reducedMotion()
    screen.current?.animate?.(
      reduce
        ? [{ opacity: 0 }, { opacity: 1 }]
        : [
            { opacity: 0, transform: `translateX(${way * 48}px)` },
            { opacity: 1, transform: 'none' }
          ],
      { duration: reduce ? 150 : 200, easing: EASING }
    )
  }, [step])

  const load = useCallback(() => {
    setFailed(null)
    window.frameflow.videos().then(
      (found) => {
        setVideos(found)
        setFolder(found[0]?.folder ?? null)
      },
      (e: Error) => setFailed(e.message)
    )
  }, [])
  useEffect(load, [load])
  // The list again, as a job or a change by hand leaves it: a title, a new video, a storyboard written.
  const refresh = useCallback(() => {
    window.frameflow.videos().then(setVideos, () => {}) // a list that cannot be read stays as it was
  }, [])

  const fresh = creating || (videos !== null && listed.length === 0) // the first video is a new one
  // A job can end after the creator has moved on, so its end reads where they are now.
  const now = useRef({ folder, watching: false, listed })
  useEffect(() => {
    now.current = { folder, watching: !settings && !fresh && step === 'prompt', listed }
  })
  const thought = (f: string, kind: ThinkRequest['kind'], done: Done, replaced: boolean): void => {
    refresh()
    const { folder: shown, watching } = now.current
    // Its storyboard and video steps read what Approve wrote, or what changed under it, again.
    if (kind === 'approve' && (done.ok || done.changed) && shown === f) setRevision((r) => r + 1)
    if (done.changed) return // the prompt step has said so
    const title = now.current.listed.find((v) => v.folder === f)?.title
    const what = kind === 'approve' ? 'storyboard' : 'plan'
    const said = done.ok ? `The ${what} is written` : `The ${what} could not be written`
    const here = watching && shown === f
    if (kind === 'approve' && done.ok) {
      if (shown === f) moving.current = 1
      setSteps((s) => ({ ...s, [f]: 'storyboard' })) // shown once the list says it has its storyboard
      // One Undo takes back the plan and the storyboard it replaced together.
      if (replaced || !here)
        say(said, { description: title, undo: replaced ? () => void putBack(f) : undefined })
    } else if (!here) say(said, { description: title })
  }
  const putBack = async (f: string): Promise<void> => {
    try {
      const { version } = await window.frameflow.describe(f)
      const answer = await window.frameflow.undo(f, version ?? '')
      if ('refused' in answer) say(answer.refused)
    } catch (e) {
      say((e as Error).message)
    }
    setRevision((r) => r + 1) // the storyboard on screen reads it again
    refresh()
  }
  const created = (f: string): void => {
    setMade((m) => [f, ...m])
    open(f)
  }
  const prompt = (f: string | null): React.JSX.Element => (
    <PromptStep
      key={f ?? 'new'}
      folder={f}
      onCreated={created}
      onThought={thought}
      onChanged={refresh}
      onSettings={() => setSettings(true)}
    />
  )

  return (
    <div className="flex h-full">
      <VideoRail
        videos={listed}
        current={settings || fresh ? null : folder} // on Settings, no video is the current one
        onOpen={open}
        onNew={() => {
          setSettings(false)
          setCreating(true)
        }}
        creating={fresh && !settings}
        settings={settings}
        onSettings={() => setSettings((shown) => !shown)}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        {settings ? (
          <SettingsPage />
        ) : fresh ? (
          <>
            <TopBar title="New video" step="prompt" ready={false} onStep={() => {}} />
            {prompt(null)}
          </>
        ) : video && folder ? (
          <>
            <TopBar title={video.title} step={step} ready={ready} onStep={go} />
            <div ref={screen} className="flex min-h-0 flex-1 flex-col">
              {step === 'prompt' ? (
                prompt(folder)
              ) : step === 'video' ? (
                <VideoStep
                  key={`${folder} ${revision}`}
                  folder={folder}
                  onGoTo={(n) => go('storyboard', n)}
                  onSettings={() => setSettings(true)}
                />
              ) : (
                <Storyboard
                  key={`${folder} ${revision}`}
                  folder={folder}
                  initialSelected={scene}
                  onSettings={() => setSettings(true)}
                  onSelected={(n) => {
                    selected.current = n
                  }}
                  footer={(state, words) => (
                    <>
                      {state.described?.video && (
                        <VideoSettings
                          folder={folder}
                          video={state.described.video}
                          edit={state.edit}
                        />
                      )}
                      {words}
                      <BuildBar
                        folder={folder}
                        described={state.described!}
                        onBuilt={state.reload}
                      />
                    </>
                  )}
                />
              )}
            </div>
          </>
        ) : (
          <div className="grid flex-1 place-items-center p-8">
            {failed ? (
              <div className="max-w-lg">
                <h1 className="text-xl font-bold tracking-[-0.015em]">
                  Frameflow&apos;s engine did not start
                </h1>
                <p role="alert" className="mt-2 select-text whitespace-pre-wrap text-signal-ink">
                  {failed}
                </p>
                <p className="mt-4 text-quiet">
                  The app runs <code>python -m project.app_api</code> in Frameflow&apos;s folder.
                  Set FRAMEFLOW_PYTHON to the Python that has Frameflow&apos;s requirements if it is
                  not the one on your PATH.
                </p>
                <Button className="mt-5 h-10 rounded-lg px-5" onClick={load}>
                  Try again
                </Button>
              </div>
            ) : null}
          </div>
        )}
      </main>
      <Toasts />
    </div>
  )
}

export default App
