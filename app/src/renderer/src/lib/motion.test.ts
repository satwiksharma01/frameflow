import { SPRING_MS, springEasing } from './motion'

const points = (easing: string): number[] =>
  easing
    .replace(/^linear\(/, '')
    .replace(/\)$/, '')
    .split(',')
    .map((v) => Number(v.trim()))

it('springEasing starts at 0, ends at exactly 1, never goes back, and has samples + 1 points', () => {
  const easing = springEasing(0.3, 20)
  expect(easing.startsWith('linear(')).toBe(true)
  const values = points(easing)
  expect(values).toHaveLength(21)
  expect(values[0]).toBe(0)
  expect(values.at(-1)).toBe(1)
  values.slice(1).forEach((v, i) => expect(v).toBeGreaterThanOrEqual(values[i]))
  expect(Math.max(...values)).toBe(1) // critically damped: no overshoot
})

it('springEasing settles: its last but one value is above 0.99', () => {
  expect(points(springEasing()).at(-2)).toBeGreaterThan(0.99)
})

it('the spring lasts about 350 ms', () => {
  expect(SPRING_MS).toBe(350)
})
