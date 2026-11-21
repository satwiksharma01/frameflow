// @vitest-environment node
import { pathToFileURL } from 'url'
import { expect, it } from 'vitest'
import { openable, ownPage } from './guard'

const dev = 'http://localhost:5173'
const built = pathToFileURL('E:/my projects/frameflow/app/out/renderer/index.html').toString()

it("the app's own page is its own, while developing and once built", () => {
  expect(ownPage(dev, 'http://localhost:5173/')).toBe(true)
  expect(ownPage(dev, 'http://localhost:5173/?video=reel#scene-3')).toBe(true)
  expect(ownPage(built, built)).toBe(true)
  expect(ownPage(built, `${built}#settings`)).toBe(true)
})

it('a dropped file, another site or another port is not', () => {
  expect(ownPage(built, pathToFileURL('C:/Users/me/Downloads/page.html').toString())).toBe(false)
  expect(ownPage(dev, pathToFileURL('C:/Users/me/Downloads/page.html').toString())).toBe(false)
  expect(ownPage(dev, 'https://example.com/')).toBe(false)
  expect(ownPage(dev, 'http://localhost:5174/')).toBe(false)
  expect(ownPage(built, 'http://localhost:5173/')).toBe(false)
  expect(ownPage(dev, '')).toBe(false)
  expect(ownPage(dev, 'not a url')).toBe(false)
})

it("only a web page opens in the creator's browser", () => {
  expect(openable('https://www.youtube.com/watch?v=x')).toBe(true)
  expect(openable('http://example.com/')).toBe(false)
  expect(openable('file:///C:/Windows/System32/calc.exe')).toBe(false)
  expect(openable('ms-settings:privacy')).toBe(false)
  expect(openable('javascript:alert(1)')).toBe(false)
  expect(openable('')).toBe(false)
})
