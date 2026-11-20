import { longVideo, tierList, twoCuts, unbuilt } from './fixture'
import { clock, numbered, summary, toView } from './model'

it('groups the scenes into the chapters the storyboard names', () => {
  const { sections } = toView(tierList)
  expect(sections.map((s) => [s.number, s.title, s.start, s.scenes.length])).toEqual([
    [1, 'Problem', 0, 5],
    [2, 'Turn', 8.7, 1],
    [3, 'Answer', 11.433, 3]
  ])
})

it('a storyboard without chapters is one unnamed section', () => {
  const { sections } = toView({ ...tierList, sections: [] })
  expect(sections.map((s) => [s.title, s.scenes.length])).toEqual([[null, 9]])
})

it("draws each scene's rule against the longest scene", () => {
  const scenes = toView(tierList).sections.flatMap((s) => s.scenes)
  expect(scenes[6].rule).toBe(1)
  expect(scenes[2].rule).toBe(0.25) // 1.2 s of 4.8
})

it('puts a suspect cut on the scene it ends, and nowhere else', () => {
  const scenes = toView(tierList).sections.flatMap((s) => s.scenes)
  expect(scenes.map((s) => s.checks.map((c) => c.what))).toEqual([
    [],
    [],
    [],
    [],
    [],
    ['May clip “work”'],
    [],
    [],
    []
  ])
})

it("a cut inside a scene that may clip a word is that scene's check", () => {
  const inside = { at: 10.0, before: ' remove all', after: ' the', heard: 'remove the' }
  const report = { ...tierList.report!, joins: { checked: 8, suspect: [inside] } }
  const scenes = toView({ ...tierList, report }).sections.flatMap((s) => s.scenes)
  expect(scenes.map((s) => s.checks)).toEqual(
    scenes.map((_, i) => (i === 5 ? [{ what: 'May clip “all”', at: 10.0 }] : []))
  )
  // A join at a scene's end still belongs to that scene, not to the one it starts.
  const ends = toView(tierList).sections.flatMap((s) => s.scenes)
  expect(ends.map((s) => s.checks.map((c) => c.at))).toEqual([
    [],
    [],
    [],
    [],
    [],
    [11.433],
    [],
    [],
    []
  ])
})

it('a scene holding two suspect cuts has both as its checks, in order, each with its own time', () => {
  const scenes = toView(twoCuts).sections.flatMap((s) => s.scenes)
  expect(scenes[5].checks).toEqual([
    { what: 'May clip “all”', at: 10.0 },
    { what: 'May clip “work”', at: 11.433 }
  ])
  expect(scenes.filter((s) => s.checks.length)).toHaveLength(1)
})

it('puts a picture problem on the scene it falls in', () => {
  const report = {
    ...tierList.report!,
    joins: null,
    picture: {
      looked: 11,
      problems: [{ at: 7.0, what: 'the graphic "Tip 1" covers 30% of a face' }]
    }
  }
  const scenes = toView({ ...tierList, report }).sections.flatMap((s) => s.scenes)
  expect(scenes[4].checks).toEqual([{ what: 'The graphic "Tip 1" covers 30% of a face', at: 7.0 }])
  expect(scenes.filter((s) => s.checks.length)).toHaveLength(1)
})

it('gives the count and the running time against the target', () => {
  expect(toView(tierList).figures).toEqual({
    scenes: 9,
    seconds: 20.1,
    target: 20,
    over: false,
    estimated: false
  })
})

it('estimates the running time of a video not built yet, with no checks', () => {
  const view = toView(unbuilt)
  expect(view.figures).toMatchObject({ estimated: true, over: false })
  expect(view.figures.seconds).toBeCloseTo(20.101, 3)
  expect(view.sections.flatMap((s) => s.scenes).every((s) => s.checks.length === 0)).toBe(true)
  expect(view.sections[1].start).toBeNull()
})

it('has no running time until every scene knows its length: part of a sum reads as the whole', () => {
  const one = unbuilt.scenes.map((s) => (s.number === 4 ? { ...s, seconds: null } : s))
  expect(toView({ ...unbuilt, scenes: one }).figures).toMatchObject({
    seconds: null,
    estimated: true,
    over: false
  })
  const none = unbuilt.scenes.map((s) => ({ ...s, seconds: null }))
  expect(toView({ ...unbuilt, scenes: none }).figures).toMatchObject({
    seconds: null,
    estimated: true,
    over: false
  })
})

it('is over when the video runs more than a tenth past its target', () => {
  const report = { ...tierList.report!, seconds: 23 }
  expect(toView({ ...tierList, report }).figures.over).toBe(true)
  expect(toView({ ...tierList, report: { ...report, seconds: 21.9 } }).figures.over).toBe(false)
})

it('writes seconds as a clock', () => {
  expect([clock(0), clock(8.7), clock(68.4), clock(600)]).toEqual(['0:00', '0:08', '1:08', '10:00'])
})

it('a video never built says so; one changed since its build says that', () => {
  expect(summary({ ...unbuilt, ever_built: false })).toBe('Not built yet.')
  expect(summary({ ...unbuilt, ever_built: true })).toBe('Not built since it last changed.')
})

it('numbers the rules only where each fits: the current one first, then the first and last, then the next', () => {
  const scenes = toView(longVideo).sections.flatMap((s) => s.scenes)
  // In a 248 px strip each of the 22 rules is about 9 px wide: 12 and 13 side by side would read "1213".
  expect(numbered(scenes, scenes[11], 248)).toEqual([12, 1, 22])
  expect(numbered(scenes, scenes[11], 1000)).toEqual([12, 1, 22, 13])
  expect(numbered(scenes, scenes[1], 248)).toEqual([2, 22]) // the current one before the first beside it
  expect(numbered(scenes, scenes[21], 248)).toEqual([22, 1])
  expect(numbered(scenes, null, 248)).toEqual([1, 22])
})
