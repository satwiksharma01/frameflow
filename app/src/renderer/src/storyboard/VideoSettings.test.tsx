import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { VideoSettings as Settings } from '@shared/types'
import type { EditResult } from './useStoryboard'
import { VideoSettings } from './VideoSettings'

const FOLDER = 'E:\\my projects\\frameflow\\output\\reference-swap'
const plain: Settings = { spoken_captions: true, has_music: false, cut_to_beat: false, look: null }

function setup(video: Settings): ReturnType<typeof vi.fn> {
  window.frameflow = { looks: vi.fn(async () => ['Warm evening.cube', 'Teal and orange']) } as never
  const edit = vi.fn(async (): Promise<EditResult> => ({ ok: true, notes: [] }))
  render(<VideoSettings folder={FOLDER} video={video} edit={edit} />)
  return edit
}

it("the captions switch shows the video's setting and sends the change", async () => {
  const edit = setup(plain)
  const captions = screen.getByRole('switch', { name: 'Word-by-word captions' })
  expect(captions).toHaveAttribute('aria-checked', 'true')
  await userEvent.click(captions)
  expect(edit).toHaveBeenCalledWith(
    { op: 'video', spoken_captions: false },
    'Word-by-word captions off'
  )
})

it('cut to the beat is offered only when the video has music', async () => {
  setup(plain)
  expect(screen.queryByRole('switch', { name: 'Cut to the beat' })).toBeNull()
})

it('cut to the beat sends its change when the video has music', async () => {
  const edit = setup({ ...plain, has_music: true })
  await userEvent.click(screen.getByRole('switch', { name: 'Cut to the beat' }))
  expect(edit).toHaveBeenCalledWith({ op: 'video', cut_to_beat: true }, 'Cut to the beat')
})

it('the look lists As shot first, then the video\u2019s looks, and As shot sends null', async () => {
  const edit = setup({ ...plain, look: 'Warm evening.cube' })
  const look = await screen.findByRole('combobox', { name: 'Look' })
  expect(look).toHaveTextContent('Warm evening.cube')
  await userEvent.click(look)
  const options = within(await screen.findByRole('listbox')).getAllByRole('option')
  expect(options.map((o) => o.textContent)).toEqual([
    'As shot',
    'Warm evening.cube',
    'Teal and orange'
  ])
  await userEvent.click(options[0])
  expect(edit).toHaveBeenCalledWith({ op: 'video', look: null }, 'Look: as shot')
})
