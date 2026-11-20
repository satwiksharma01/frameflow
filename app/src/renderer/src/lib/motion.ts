// The one spring the app moves things with: critically damped, so it settles without overshoot, as
// Apple's interfaces do for anything that is not thrown. CSS cannot run a spring, so it is sampled into a
// `linear()` easing; CSS transitions start again from where an element is, so a move can be interrupted.

/** How long a spring move lasts. */
export const SPRING_MS = 350

/** A CSS `linear()` easing for a critically damped spring: x(t) = 1 - (1 + ωt)e^(-ωt), ω = 2π / response. */
export function springEasing(response = 0.3, samples = 20): string {
  const omega = (2 * Math.PI) / response
  const values = Array.from({ length: samples + 1 }, (_, i) => {
    const t = (i / samples) * (SPRING_MS / 1000)
    return 1 - (1 + omega * t) * Math.exp(-omega * t)
  })
  values[samples] = 1
  return `linear(${values.map((v) => Number(v.toFixed(4))).join(', ')})`
}

/** Whether the creator has asked for less motion. */
export function reducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}
