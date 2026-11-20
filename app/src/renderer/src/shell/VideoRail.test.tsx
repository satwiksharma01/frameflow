import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Video } from '@shared/types'
import { VideoRail } from './VideoRail'

const videos: Video[] = Array.from({ length: 16 }, (_, i) => ({
  folder: `E:\\videos\\${i}`,
  title: `Video ${i + 1}`,
  has_storyboard: true,
  built: false,
  cover: null
}))

it('only the videos scroll: the gear stays at the foot of the rail', () => {
  window.frameflow = { thumbnail: async () => null } as never
  render(
    <VideoRail
      videos={videos}
      current={null}
      onOpen={() => {}}
      onNew={() => {}}
      creating={false}
      settings={false}
      onSettings={() => {}}
    />
  )
  const scrolls = (name: string): Element | null =>
    screen.getByRole('button', { name }).closest('[class*="overflow-y-auto"]')
  expect(scrolls('Video 16')).not.toBeNull()
  expect(scrolls('Settings')).toBeNull()
})

it('the + is New video: it follows the videos, outside their scrolling list, so it stays in reach', async () => {
  window.frameflow = { thumbnail: async () => null } as never
  const onNew = vi.fn()
  render(
    <VideoRail
      videos={videos}
      current={null}
      onOpen={() => {}}
      onNew={onNew}
      creating={false}
      settings={false}
      onSettings={() => {}}
    />
  )
  const plus = screen.getByRole('button', { name: 'New video' })
  expect(plus.closest('[class*="overflow-y-auto"]')).toBeNull()
  const order = screen.getAllByRole('button').map((b) => b.getAttribute('aria-label'))
  expect(order.slice(-3)).toEqual(['Video 16', 'New video', 'Settings'])
  await userEvent.click(plus)
  expect(onNew).toHaveBeenCalledTimes(1)
  expect(plus).not.toHaveAttribute('aria-current')
})
