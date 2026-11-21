// The tier-list reel (output/reference-swap), as project.app_api describes it once built, with the
// chapters and the build report the screen was designed around. Test data; the app never ships it.
import type { Described, Scene } from '@shared/types'

const SCENES: [number, number, string, string][] = [
  [0, 1.467, 'main problem with video editing', '0:45–0:47'],
  [1.467, 1.8, "there's just a lot of boring work", '0:50–0:52'],
  [3.267, 1.2, 'you say this', '1:01–1:02'],
  [4.467, 2.467, 'same thing three times like this', '1:03–1:05'],
  [6.933, 1.767, 'video editing takes a lot of time', '1:05–1:07'],
  [8.7, 2.733, 'the goal is to remove all the repetitive editing work', '5:12–5:15'],
  [
    11.433,
    4.8,
    'create a complete first cut instead of spending an hour editing a reel you could start with something that',
    '4:05–4:10'
  ],
  [16.233, 1.9, 'already almost finished', '4:11–4:12'],
  [18.133, 1.967, 'I still want the human to have control', '4:40–4:41']
]

const scenes: Scene[] = SCENES.map(([start, seconds, says, span], i) => ({
  number: i + 1,
  kind: 'footage',
  says,
  seconds,
  start,
  source: `Your recording ${span}`,
  over: [],
  text: null,
  key: `scene-${i + 1}`,
  narration: null,
  caption: null,
  cards: [],
  broll: []
}))

export const tierList: Described = {
  title: 'Editing tier list',
  aspect: '9:16',
  target_seconds: 20,
  built: true,
  version: 'v1',
  can_undo: false,
  can_redo: false,
  video: { spoken_captions: true, has_music: false, cut_to_beat: false, look: null },
  sections: [
    { title: 'Problem', from: 1 },
    { title: 'Turn', from: 6 },
    { title: 'Answer', from: 7 }
  ],
  scenes,
  report: {
    seconds: 20.1,
    target_seconds: 20,
    scenes: scenes.map((s) => ({ start: s.start!, end: s.start! + s.seconds! })),
    joins: {
      checked: 8,
      suspect: [
        { at: 11.433, before: ' editing work', after: ' create a', heard: 'editing or create' }
      ]
    },
    picture: { looked: 11, problems: [] }
  }
}

/** The same video before any build: no report, no start times, lengths only where the spans say them. */
export const unbuilt: Described = {
  ...tierList,
  built: false,
  report: null,
  scenes: scenes.map((s) => ({ ...s, start: null }))
}

/** The same video built with two suspect cuts in scene 6: one inside it, where a long pause was cut, and
 *  its end. */
export const twoCuts: Described = {
  ...tierList,
  report: {
    ...tierList.report!,
    joins: {
      checked: 8,
      suspect: [
        { at: 11.433, before: ' editing work', after: ' create a', heard: 'editing or create' },
        { at: 10.0, before: ' remove all', after: ' the', heard: 'remove the' }
      ]
    }
  }
}

const EVEN = Array.from({ length: 22 }, (_, i) => ({ start: i * 27, end: i * 27 + 27 }))

/** A long video, built: 22 scenes of 27 s, as many as the 10-minute check had, with no chapters. */
export const longVideo: Described = {
  ...tierList,
  sections: [],
  scenes: EVEN.map((span, i) => ({
    ...scenes[0],
    number: i + 1,
    key: `scene-${i + 1}`,
    start: span.start,
    seconds: 27
  })),
  report: { ...tierList.report!, seconds: 594, scenes: EVEN, joins: { checked: 21, suspect: [] } }
}
