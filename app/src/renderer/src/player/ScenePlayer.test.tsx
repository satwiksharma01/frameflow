import { fireEvent, render, waitFor } from '@testing-library/react'
import { ScenePlayer } from './ScenePlayer'

const SRC = 'ff-media://preview/?p=x'

function at(video: HTMLVideoElement, seconds: number): void {
  video.currentTime = seconds
  fireEvent.timeUpdate(video)
}

it('it starts at from and stops at to, once', () => {
  const onEnd = vi.fn()
  const { container } = render(<ScenePlayer src={SRC} from={8.7} to={11.433} onEnd={onEnd} />)
  const video = container.querySelector('video')!
  expect(video).toHaveAttribute('src', SRC)
  expect(video.currentTime).toBe(8.7)
  expect(video.paused).toBe(false)
  at(video, 11.4)
  expect(onEnd).not.toHaveBeenCalled()
  at(video, 11.433)
  expect(video.paused).toBe(true)
  expect(onEnd).toHaveBeenCalledTimes(1)
  at(video, 11.5)
  expect(onEnd).toHaveBeenCalledTimes(1)
})

it('a new from seeks again', () => {
  const props = { src: SRC, to: 20, onEnd: () => {} }
  const { container, rerender } = render(<ScenePlayer {...props} from={1} />)
  const video = container.querySelector('video')!
  at(video, 5)
  rerender(<ScenePlayer {...props} from={9.933} />)
  expect(video.currentTime).toBe(9.933)
})

it('a video that ends before to ends the stretch too', () => {
  const onEnd = vi.fn()
  const { container } = render(<ScenePlayer src={SRC} from={18} to={20.1} onEnd={onEnd} />)
  fireEvent.ended(container.querySelector('video')!)
  expect(onEnd).toHaveBeenCalledTimes(1)
})

it('paused, it holds the frame at from and plays nothing', () => {
  const onEnd = vi.fn()
  const { container } = render(<ScenePlayer src={SRC} from={8.7} to={20.1} paused onEnd={onEnd} />)
  const video = container.querySelector('video')!
  expect(video.currentTime).toBe(8.7)
  expect(video.paused).toBe(true)
  at(video, 20.1)
  expect(onEnd).not.toHaveBeenCalled()
})

it('it says the time as it plays, and a new run seeks again though from is the same', () => {
  const onTime = vi.fn()
  const props = { src: SRC, from: 8.7, to: 20.1, onEnd: () => {}, onTime }
  const { container, rerender } = render(<ScenePlayer {...props} run={{}} />)
  const video = container.querySelector('video')!
  at(video, 9.4)
  expect(onTime).toHaveBeenLastCalledWith(9.4)
  rerender(<ScenePlayer {...props} run={{}} />)
  expect(video.currentTime).toBe(8.7)
})

it('a preview that cannot play ends at once', async () => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValueOnce(new Error('NotSupportedError'))
  const onEnd = vi.fn()
  render(<ScenePlayer src={SRC} from={8.7} to={11.433} onEnd={onEnd} />)
  await waitFor(() => expect(onEnd).toHaveBeenCalledTimes(1))
})
