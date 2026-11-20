import { useEffect, useEffectEvent, useRef } from 'react'
import { cn } from '@/lib/utils'

/** Listen plays from a second and a half before a check's moment to a second after it. */
export const LISTEN_BEFORE = 1.5
export const LISTEN_AFTER = 1.0

interface Props {
  src: string
  from: number
  to: number
  /** Called once, when the stretch is over. */
  onEnd(): void
  /** Held at `from` without playing, as a paused player shows its frame. */
  paused?: boolean
  /** Told the time as it plays. */
  onTime?(seconds: number): void
  /** A new value plays the stretch again from `from`, though from and to are as before. */
  run?: object
  className?: string
}

/** One stretch of the preview, picture and sound: it starts at `from` and pauses itself at `to`. */
export function ScenePlayer({
  src,
  from,
  to,
  onEnd,
  paused = false,
  onTime,
  run,
  className
}: Props): React.JSX.Element {
  const video = useRef<HTMLVideoElement>(null)
  const ended = useEffectEvent(onEnd)
  const timed = useEffectEvent((seconds: number) => onTime?.(seconds))

  useEffect(() => {
    const element = video.current!
    element.currentTime = from
    if (paused) {
      element.pause()
      return
    }
    let over = false
    let frame = 0
    const end = (): void => {
      if (over) return
      over = true
      element.pause()
      ended()
    }
    const check = (): void => {
      timed(element.currentTime)
      if (element.currentTime >= to) end()
    }
    // timeupdate comes a few times a second; a frame's callback stops it on the frame itself.
    const watch = (): void => {
      check()
      if (!over) frame = element.requestVideoFrameCallback(watch)
    }
    element.play().catch(end) // one that cannot play is over at once
    element.addEventListener('timeupdate', check)
    element.addEventListener('ended', end) // a stretch to the end may reach past the video's last frame
    if ('requestVideoFrameCallback' in element) frame = element.requestVideoFrameCallback(watch)
    return () => {
      over = true
      element.removeEventListener('timeupdate', check)
      element.removeEventListener('ended', end)
      if (frame) element.cancelVideoFrameCallback(frame)
    }
  }, [src, from, to, paused, run])

  return <video ref={video} src={src} className={cn('bg-black object-cover', className)} />
}
