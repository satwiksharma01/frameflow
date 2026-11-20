import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'

// jsdom has no IntersectionObserver. By default everything observed is in view at once; a test that
// needs to scroll sets `observers.auto = false` and calls `observers.show(element)` itself.
export const observers = {
  auto: true,
  watching: new Map<Element, IntersectionObserverCallback>(),
  show(element: Element): void {
    this.watching.get(element)?.(
      [{ isIntersecting: true, target: element } as IntersectionObserverEntry],
      {} as IntersectionObserver
    )
  }
}

/** Radix's menus and dialogs play a closing animation in Chrome, and hand the focus back only when it
 *  ends; jsdom has no animations, so they close at once. This gives every element Radix opens and closes
 *  an animation, as Chrome does, that ends when the test calls `finish()`. */
export function slowExits(): { finish(): void } {
  const real = window.getComputedStyle.bind(window)
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element, pseudo) => {
    const styles = real(element, pseudo)
    if (!(element instanceof HTMLElement) || !element.hasAttribute('data-state')) return styles
    return new Proxy(styles, {
      get(target, key) {
        if (key === 'animationName') return element.dataset.state === 'closed' ? 'exit' : 'enter'
        const value = Reflect.get(target, key)
        return typeof value === 'function' ? value.bind(target) : value
      }
    })
  })
  globalThis.CSS ??= { escape: (s: string) => s } as never
  return {
    finish: () =>
      document
        .querySelectorAll('[data-state=closed]')
        .forEach((element) =>
          element.dispatchEvent(Object.assign(new Event('animationend'), { animationName: 'exit' }))
        )
  }
}

class FakeObserver {
  constructor(private callback: IntersectionObserverCallback) {}
  observe(element: Element): void {
    observers.watching.set(element, this.callback)
    if (observers.auto) observers.show(element)
  }
  unobserve(element: Element): void {
    observers.watching.delete(element)
  }
  disconnect(): void {}
}

beforeEach(() => {
  if (typeof Element === 'undefined') return // a main-process test, with no page
  observers.auto = true
  observers.watching.clear()
  globalThis.IntersectionObserver = FakeObserver as never
  Element.prototype.scrollIntoView = () => {}
  // jsdom has no pointer capture; toasts and drags ask for it.
  Element.prototype.setPointerCapture = () => {}
  Element.prototype.releasePointerCapture = () => {}
  Element.prototype.hasPointerCapture = () => false
  // Nor media playback: play() starts at once and pause() stops, and a test moves the time itself.
  HTMLMediaElement.prototype.play = function () {
    Object.defineProperty(this, 'paused', { value: false, configurable: true })
    return Promise.resolve()
  }
  HTMLMediaElement.prototype.pause = function () {
    Object.defineProperty(this, 'paused', { value: true, configurable: true })
  }
  // Nor ResizeObserver, which menus measure their trigger with.
  globalThis.ResizeObserver ??= class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  } as never
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})
