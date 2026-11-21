import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { SHAPES } from './shapes'

// One request per picture, shared by the scene's module and the details panel. A picture is asked for by
// its scene's key, which stays with the scene as scenes move. Kept per engine, so a
// different engine (a test's) starts with none.
const asked = new WeakMap<object, Map<string, Promise<string | null>>>()

function pictures(): Map<string, Promise<string | null>> {
  if (!asked.has(window.frameflow)) asked.set(window.frameflow, new Map())
  return asked.get(window.frameflow)!
}

function picture(folder: string, pictureKey: string): Promise<string | null> {
  const key = `${pictureKey}|${folder}`
  const known = pictures()
  if (!known.has(key))
    known.set(
      key,
      window.frameflow.thumbnail(folder, pictureKey).catch(() => null)
    )
  return known.get(key)!
}

interface Props {
  folder: string
  number: number
  /** The scene's key, by which its picture is asked for; null for none. */
  pictureKey: string | null
  aspect?: keyof typeof SHAPES | null
  className?: string
  /** What a frame with no picture shows; the scene's number when not given. */
  plain?: string
  /** A title scene's words: the frame is drawn as the title card, and no picture is asked for. */
  title?: string | null
}

/** A scene's picture in the video's shape. It is asked for only once the frame nears the viewport;
 *  a scene with no picture of its own shows its number on a plain frame. */
export function Thumbnail({
  folder,
  number,
  pictureKey,
  aspect,
  className,
  plain,
  title
}: Props): React.JSX.Element {
  const frame = useRef<HTMLDivElement>(null)
  const [near, setNear] = useState(false)
  const [src, setSrc] = useState<string | null | undefined>(undefined)

  useEffect(() => {
    const element = frame.current!
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setNear(true)
          observer.disconnect()
        }
      },
      { rootMargin: '400px' }
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!near || title || !pictureKey) return
    let current = true
    picture(folder, pictureKey).then((url) => current && setSrc(url))
    return () => {
      current = false
    }
  }, [near, folder, pictureKey, title])
  // A scene with no picture of its own shows its plain frame once it is near.
  const shown = near && !pictureKey ? null : src

  return (
    <div
      ref={frame}
      data-frame={title ? 'title' : shown ? 'picture' : shown === null ? 'plain' : 'waiting'}
      className={cn(
        'grid flex-none place-items-center overflow-hidden',
        title ? 'bg-black' : 'bg-plain',
        SHAPES[aspect ?? '9:16'],
        className
      )}
    >
      {title ? (
        <span className="line-clamp-4 px-[8%] text-center text-[clamp(8px,0.6em,15px)] font-bold leading-tight">
          {title}
        </span>
      ) : shown ? (
        <img
          src={shown}
          alt=""
          role="presentation"
          draggable={false}
          className="size-full object-cover"
        />
      ) : shown === null ? (
        <span className="text-[15px] font-bold text-quiet">{plain ?? number}</span>
      ) : null}
    </div>
  )
}
