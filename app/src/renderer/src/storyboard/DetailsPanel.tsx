import { Headphones, ImageUp, Trash2 } from 'lucide-react'
import { useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import type { Described, EditOp } from '@shared/types'
import { LISTEN_AFTER, LISTEN_BEFORE, ScenePlayer } from '../player/ScenePlayer'
import type { SceneView } from './model'
import { OverEditor } from './OverEditor'
import { SHAPES, Thumbnail } from './Thumbnail'
import type { EditResult } from './useStoryboard'
import { WordsField, type WordsFieldHandle } from './WordsField'

export interface DetailsPanelHandle {
  /** Open the selected scene's words for typing. */
  focusWords(): void
  /** Put the cursor in a title's words on screen. */
  focusTitle(): void
  /** Play the preview from one second of the video to another in the scene's frame. */
  play(from: number, to: number): void
  /** Show the scene's picture again. */
  stop(): void
  /** Play around the scene's first check, as its Listen button does. */
  listen(): void
  /** Whether the frame is playing. */
  playing: boolean
}

interface Props {
  scene: SceneView
  folder: string
  aspect: Described['aspect']
  /** The last build's preview, while it is of the storyboard as it is now. */
  preview?: string | null
  edit(op: EditOp, toast?: string): Promise<EditResult>
  /** Called once a field is sent with Enter or let go with Esc, or Listen is over, to give the focus
   *  back to the scenes. */
  onDone?(): void
  ref?: Ref<DetailsPanelHandle>
}

function Row({ label, children }: { label: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div className="flex items-baseline justify-between gap-6 text-[12px]">
      <dt className="flex-none text-quiet">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </div>
  )
}

/** A title's words on screen: sent when the field is left, or on Enter. */
function OnScreen({
  text,
  onCommit,
  onDone,
  ref
}: {
  text: string
  onCommit(text: string): void
  onDone?(): void
  ref?: Ref<HTMLInputElement>
}): React.JSX.Element {
  const [draft, setDraft] = useState(text)
  return (
    <label className="mt-4 block">
      <span className="text-[12px] text-quiet">On screen</span>
      <Input
        ref={ref}
        aria-label="On screen"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => draft.trim() && draft.trim() !== text && onCommit(draft.trim())}
        onKeyDown={(e) => {
          if (e.key !== 'Enter' || e.nativeEvent.isComposing) return
          e.currentTarget.blur() // which sends the words
          onDone?.()
        }}
        className="mt-1 h-9 rounded-md text-[15px]"
      />
    </label>
  )
}

/** The selected scene, larger, and everything about it the creator can change: its words, a title's words
 *  on screen, its picture, what pops up over it, and the scene itself. */
export function DetailsPanel({
  scene,
  folder,
  aspect,
  preview,
  edit,
  onDone,
  ref
}: Props): React.JSX.Element {
  const words = useRef<WordsFieldHandle>(null)
  const onScreen = useRef<HTMLInputElement>(null)
  const listenButton = useRef<HTMLButtonElement>(null) // the Listen last pressed
  const [playing, setPlaying] = useState<{ from: number; to: number } | null>(null)
  // What plays is of this scene and this preview: another scene, or a change, shows the picture again.
  useEffect(() => setPlaying(null), [scene.key, preview])
  const stop = (): void => {
    setPlaying(null)
    if (document.activeElement === listenButton.current) onDone?.()
  }
  const listen = (at = scene.checks[0]?.at): void => {
    if (at === undefined) return
    setPlaying({ from: at - LISTEN_BEFORE, to: at + LISTEN_AFTER })
  }
  useImperativeHandle(ref, () => ({
    focusWords: () => words.current?.open(),
    focusTitle: () => {
      onScreen.current?.focus()
      onScreen.current?.select()
    },
    play: (from, to) => setPlaying({ from, to }),
    stop,
    listen,
    playing: playing !== null
  }))
  const frame =
    aspect === '16:9' ? 'mt-5 w-full rounded-xl text-[26px]' : 'mt-5 w-40 rounded-xl text-[20px]'
  const heard = scene.kind === 'footage' && !scene.narration // its words are where the recording says them

  const replacePicture = async (): Promise<void> => {
    const path = await window.frameflow.chooseFile()
    if (path) await edit({ op: 'picture', number: scene.number, path }, 'Picture replaced')
  }

  return (
    <aside
      aria-label={`Scene ${scene.number}`}
      className="w-[340px] flex-none overflow-y-auto border-l p-6"
    >
      <div className="flex items-start">
        {/* The panel's heading, so its "Over it" follows on whether or not the scenes have chapters. */}
        <h2 className="text-[56px] font-bold leading-[0.9] tracking-[-0.035em]">
          {String(scene.number).padStart(2, '0')}
        </h2>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Delete scene"
          title="Delete scene"
          onClick={() =>
            void edit({ op: 'delete', number: scene.number }, `Scene ${scene.number} deleted`)
          }
          className="ml-auto size-8 rounded-md text-quiet hover:text-ink"
        >
          <Trash2 aria-hidden />
        </Button>
      </div>
      {playing && preview && (
        <ScenePlayer
          src={preview}
          from={playing.from}
          to={playing.to}
          onEnd={stop}
          className={cn(frame, SHAPES[aspect ?? '9:16'])}
        />
      )}
      {/* Kept while the player is shown, so the picture is back at once. */}
      <Thumbnail
        key={scene.key}
        folder={folder}
        number={scene.number}
        pictureKey={scene.key}
        aspect={aspect}
        title={scene.text}
        className={cn(frame, playing && preview && 'hidden')}
      />
      <WordsField
        key={`${scene.key}-words`}
        ref={words}
        label={heard ? 'What is said' : 'What the voice says'}
        hint={heard ? 'Change the words to use another part of your recording' : undefined}
        looking={heard ? 'Finding it in your recording…' : undefined}
        words={heard || scene.narration ? scene.says : ''}
        onCommit={(text) => edit({ op: 'words', number: scene.number, words: text })}
        onDone={onDone}
      />
      {scene.kind === 'title' && (
        <OnScreen
          ref={onScreen}
          key={`${scene.key}-title`}
          text={scene.text ?? ''}
          onCommit={(text) => void edit({ op: 'title', number: scene.number, text })}
          onDone={onDone}
        />
      )}
      <dl className="mt-4 grid gap-3">
        <Row label="Picture">{scene.source}</Row>
        {scene.checks.map((check, i) => (
          <Row key={i} label="Check">
            <span className="text-signal-ink">{check.what}</span>
            {preview && (
              <Button
                type="button"
                variant="ghost"
                onClick={(e) => {
                  listenButton.current = e.currentTarget
                  listen(check.at)
                }}
                className="-mr-2 ml-1 h-8 rounded-md px-2 text-[13px]"
              >
                <Headphones aria-hidden />
                Listen
              </Button>
            )}
          </Row>
        ))}
      </dl>
      <Button
        type="button"
        variant="ghost"
        onClick={() => void replacePicture()}
        className="mt-2 h-8 rounded-md px-2 text-[13px]"
      >
        <ImageUp aria-hidden />
        {scene.kind === 'footage' ? 'Cover with a picture or clip…' : 'Replace the picture…'}
      </Button>
      <OverEditor key={`${scene.key}-over`} scene={scene} edit={edit} onDone={onDone} />
    </aside>
  )
}
