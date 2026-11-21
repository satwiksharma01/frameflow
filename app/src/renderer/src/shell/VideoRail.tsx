import { Plus, Settings } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Video } from '@shared/types'
import { Thumbnail } from '../storyboard/Thumbnail'

interface Props {
  videos: Video[]
  current: string | null
  onOpen: (folder: string) => void
  onNew: () => void
  /** Whether a new video, with no folder yet, is the page shown. */
  creating: boolean
  /** Whether Settings is the page shown. */
  settings: boolean
  onSettings: () => void
}

/** The creator's videos down the left edge, each by its first scene's picture, newest first, then
 *  New video, and Settings at its foot. */
export function VideoRail({
  videos,
  current,
  onOpen,
  onNew,
  creating,
  settings,
  onSettings
}: Props): React.JSX.Element {
  return (
    <nav
      aria-label="Videos"
      className="flex w-14 flex-none flex-col items-center gap-3 border-r py-3.5"
    >
      <div
        aria-hidden
        className="mb-2 grid size-8 flex-none place-items-center rounded-md bg-ink text-[13px] font-bold text-ground"
      >
        F
      </div>
      {/* Only the videos scroll, so New video follows them and the gear stays at the foot, both in reach
          however many videos there are. The padding keeps a video's outline whole. */}
      <div className="-my-1.5 flex min-h-0 w-full flex-initial flex-col items-center gap-3 overflow-y-auto py-1.5 [scrollbar-width:none]">
        {videos.map((video) => (
          <button
            key={video.folder}
            type="button"
            title={video.title}
            aria-label={video.title}
            aria-current={video.folder === current ? 'page' : undefined}
            onClick={() => onOpen(video.folder)}
            className={cn(
              'flex-none scroll-my-1.5 cursor-pointer rounded-sm outline-offset-[3px] transition-opacity duration-150',
              video.folder === current
                ? 'outline outline-[1.5px] outline-ink'
                : 'opacity-45 hover:opacity-80'
            )}
          >
            <Thumbnail
              folder={video.folder}
              number={1}
              pictureKey={video.cover}
              plain={video.title.charAt(0).toUpperCase()}
              className="w-8 rounded-sm [&>span]:text-[12px]"
            />
          </button>
        ))}
      </div>
      <button
        type="button"
        title="New video"
        aria-label="New video"
        aria-current={creating ? 'page' : undefined}
        onClick={onNew}
        className="grid size-8 flex-none cursor-pointer place-items-center rounded-md border border-ink text-ink transition-colors duration-150 hover:bg-plain"
      >
        <Plus aria-hidden className="size-4" />
      </button>
      <button
        type="button"
        title="Settings"
        aria-label="Settings"
        aria-current={settings ? 'page' : undefined}
        onClick={onSettings}
        className={cn(
          'mt-auto grid size-8 flex-none cursor-pointer place-items-center rounded-md border transition-colors duration-150',
          settings ? 'border-ink text-ink' : 'border-dim text-quiet hover:text-ink'
        )}
      >
        <Settings aria-hidden className="size-4" />
      </button>
    </nav>
  )
}
