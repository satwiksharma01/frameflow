// @vitest-environment node
import { readFileSync } from 'fs'
import { expect, it } from 'vitest'

it('reduced motion stops a looping animation rather than speeding it up', () => {
  const css = readFileSync('src/renderer/src/styles/tokens.css', 'utf8')
  const reduced = css.slice(css.indexOf('prefers-reduced-motion'))
  expect(reduced).toMatch(/animation-iteration-count:\s*1\s*!important/)
})
