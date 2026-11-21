import { useEffect, useId, useState } from 'react'
import { say } from '../shell/say'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import type { EditOp, VideoSettings as Settings } from '@shared/types'
import type { EditResult } from './useStoryboard'

const AS_SHOT = '\u0000as-shot' // a select item needs a value; no look is named this

interface Props {
  folder: string
  video: Settings
  edit(op: EditOp, toast?: string): Promise<EditResult>
}

/** What applies to the whole video, at the footer's left: captions, cutting to the music, and the look. */
export function VideoSettings({ folder, video, edit }: Props): React.JSX.Element {
  const id = useId()
  const [looks, setLooks] = useState<string[]>([])
  useEffect(() => {
    window.frameflow.looks(folder).then(setLooks, () => setLooks([]))
  }, [folder])
  // The video's own look stays listed while the names load, or if it has gone from the folder.
  const names = video.look && !looks.includes(video.look) ? [...looks, video.look] : looks

  const send = (op: EditOp, said: string): void =>
    void edit(op, said).then((result) => {
      if (!result.ok) say(result.refused)
    })

  return (
    <div className="flex flex-none items-center gap-5 whitespace-nowrap text-[12px]">
      <label htmlFor={`${id}-captions`} className="flex min-h-8 cursor-pointer items-center gap-2">
        <Switch
          id={`${id}-captions`}
          checked={video.spoken_captions}
          onCheckedChange={(on) =>
            send({ op: 'video', spoken_captions: on }, `Word-by-word captions ${on ? 'on' : 'off'}`)
          }
        />
        Word-by-word captions
      </label>
      {video.has_music && (
        <label htmlFor={`${id}-beat`} className="flex min-h-8 cursor-pointer items-center gap-2">
          <Switch
            id={`${id}-beat`}
            checked={video.cut_to_beat}
            onCheckedChange={(on) =>
              send(
                { op: 'video', cut_to_beat: on },
                on ? 'Cut to the beat' : 'No longer cut to the beat'
              )
            }
          />
          Cut to the beat
        </label>
      )}
      <span className="flex items-center gap-2">
        <label htmlFor={`${id}-look`}>Look</label>
        <Select
          value={video.look ?? AS_SHOT}
          onValueChange={(value) => {
            const look = value === AS_SHOT ? null : value
            send({ op: 'video', look }, `Look: ${look ?? 'as shot'}`)
          }}
        >
          <SelectTrigger
            id={`${id}-look`}
            size="sm"
            className="h-8 max-w-44 rounded-md text-[12px]"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="rounded-xl">
            <SelectItem value={AS_SHOT}>As shot</SelectItem>
            {names.map((name) => (
              <SelectItem key={name} value={name}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </span>
    </div>
  )
}
