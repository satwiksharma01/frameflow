// What the engine (project/app_api.py) tells the app, and what the renderer may ask of the main process.

export interface Video {
  folder: string
  title: string
  has_storyboard: boolean
  built: boolean
  /** The key of the video's first scene, for its picture in the rail; null without a storyboard. */
  cover: string | null
}

export interface Card {
  kind: 'product' | 'lower_third'
  text: string
  subtitle?: string
  price?: string
  when?: string
  duration?: number
}

export interface Broll {
  path: string
  when?: string
  duration?: number
  start?: number
}

export interface Scene {
  number: number
  kind: 'footage' | 'asset' | 'title' | 'composition' | 'generated'
  says: string
  seconds: number | null
  start: number | null
  source: string
  over: string[]
  /** A title's words on screen; null for every other kind of scene. */
  text: string | null
  /** A name that stays with the scene as scenes move; its picture is asked for by it. */
  key: string
  narration: string | null
  caption: string | null
  cards: Card[]
  broll: Broll[]
}

export interface Section {
  title: string
  from: number
  /** True once the creator has renamed or kept a chapter the editor suggested. */
  confirmed?: boolean
}

export interface SuspectJoin {
  at: number
  before: string
  after: string
  heard: string
}

export interface Report {
  seconds: number
  target_seconds: number
  scenes: { start: number; end: number }[]
  joins: { checked: number; suspect: SuspectJoin[] } | { skipped: string } | null
  picture: { looked: number; problems: { at: number | null; what: string }[] } | { skipped: string }
  /** The preview's file name, or why none was made; absent in a report from before previews. */
  preview?: string | { skipped: string }
}

export interface VideoSettings {
  spoken_captions: boolean
  has_music: boolean
  cut_to_beat: boolean
  /** The look's file name, or null for the picture as shot. */
  look: string | null
}

export interface Described {
  title: string
  aspect?: '16:9' | '9:16' | '1:1' | null
  target_seconds?: number | null
  built?: boolean
  /** Whether a build has left the video's OpenShot project, whether or not it is of the storyboard now. */
  ever_built?: boolean
  sections?: Section[]
  scenes: Scene[]
  report?: Report | null
  no_storyboard?: true
  /** The storyboard as it was read; every change is sent with it. */
  version?: string
  can_undo?: boolean
  can_redo?: boolean
  video?: VideoSettings
  /** The last build's preview as an `ff-media` URL, only while it is of the storyboard as it is now. */
  preview?: string | null
  /** The plan: its draft while there is one, else the approved brief; null before one is written. */
  plan?: Plan | null
  plan_is_draft?: boolean
  /** The plan's facts (from 1) whose page Frameflow could not open. */
  plan_unopened?: number[]
  /** The idea and the material the video was prepared from, the files by name. */
  prompt?: string | null
  material?: {
    footage: string[]
    assets: string[]
    music: string[]
    looks: string[]
    script: boolean
  }
}

/** The plan is the brief (project/schema/brief.schema.json). */
export interface Plan {
  title: string
  format: string
  aspect: '16:9' | '9:16' | '1:1'
  target_seconds: number
  audience: string
  tone: string
  summary: string
  facts?: { claim: string; source: string; url: string; quote: string }[]
  open_questions?: string[]
}

export type NewScene =
  | { kind: 'title'; text: string }
  | { kind: 'file'; path: string }
  | { kind: 'recording'; words: string }

export type EditOp =
  | { op: 'move'; from: number; to: number }
  | { op: 'delete'; number: number }
  | { op: 'add'; after: number; scene: NewScene }
  | { op: 'words'; number: number; words: string }
  | { op: 'title'; number: number; text: string }
  | { op: 'over'; number: number; caption?: string | null; cards?: Card[]; broll?: Broll[] }
  | { op: 'picture'; number: number; path: string }
  | { op: 'rename_chapter'; number: number; title: string }
  | { op: 'keep_chapter'; number: number }
  | { op: 'remove_chapter'; number: number }
  | { op: 'video'; spoken_captions?: boolean; cut_to_beat?: boolean; look?: string | null }

export type EditAnswer =
  { described: Described; notes: string[] } | { refused: string; changed: boolean }

export type BuildEvent =
  | { type: 'step'; text: string }
  | { type: 'detail'; text: string }
  /** The report and its checks are written; the preview follows in the same run. */
  | { type: 'built' }
  /** A thinking job adds what it made (`result`), that the storyboard changed outside the app (`changed`),
   *  or that the thinker said the change cannot be made in words (`refused`). A job the creator stopped
   *  says so (`stopped`). */
  | {
      type: 'done'
      ok: boolean
      message?: string
      result?: Record<string, unknown>
      changed?: true
      refused?: true
      stopped?: true
    }

export type Thinking = 'auto' | 'agent:claude' | 'agent:opencode' | 'key'

export interface Settings {
  thinking: Thinking
  service?: 'anthropic' | 'openai' | 'openrouter' | 'gemini' | 'custom'
  model?: string
  baseUrl?: string
}

/** What the settings page is shown. The key itself never leaves the main process: only whether one is kept. */
export interface SettingsView extends Settings {
  hasKey: boolean
  agents: { id: string; name: string; found: boolean; version: string | null }[]
}

export type ThinkRequest =
  | {
      kind: 'start'
      prompt: string
      footage: string[]
      assets: string[]
      music: string[]
      looks: string[]
      script?: string
      shape?: string
    }
  | { kind: 'plan-change'; words: string }
  | { kind: 'answer'; question: number; words: string }
  | { kind: 'approve' }
  | { kind: 'change'; words: string; version: string }

export interface FrameflowApi {
  videos(): Promise<Video[]>
  describe(folder: string): Promise<Described>
  /** A URL the renderer can show for the scene with this key, or null when it has no picture of its own. */
  thumbnail(folder: string, key: string): Promise<string | null>
  edit(folder: string, op: EditOp, version: string): Promise<EditAnswer>
  undo(folder: string, version: string): Promise<EditAnswer>
  redo(folder: string, version: string): Promise<EditAnswer>
  /** The names of the looks this video can use. */
  looks(folder: string): Promise<string[]>
  /** A picture or clip the creator picks in the file dialog, or null when they cancel. */
  chooseFile(): Promise<string | null>
  build(folder: string, onEvent: (e: BuildEvent) => void): Promise<void>
  /** Opens the built project in OpenShot, reporting its steps as a build does. */
  open(folder: string, onEvent: (e: BuildEvent) => void): Promise<void>
  onBuildFinished(cb: (folder: string, ok: boolean) => void): void
  /** The settings, with the agents found once a session; `fresh` looks for them again. */
  settings(fresh?: boolean): Promise<SettingsView>
  saveSettings(s: Settings): Promise<void>
  saveKey(key: string): Promise<void>
  forgetKey(): Promise<void>
  /** Asks the chosen thinker for one answer. Its last detail is `Ready: <the thinker's name>`. */
  testThinking(onEvent: (e: BuildEvent) => void): Promise<void>
  /** Makes a folder for a new video from its prompt, and returns it. */
  newVideo(prompt: string): Promise<string>
  /** A thinking job. Its `done` event carries `result` for approve and change, and `changed` when refused. */
  think(folder: string, request: ThinkRequest, onEvent: (e: BuildEvent) => void): Promise<void>
  /** Stops the video's build or thinking job; it ends with a `done` that says `stopped`. */
  stop(job: 'build' | 'think', folder: string): Promise<boolean>
  editPlan(folder: string, fields: Record<string, unknown>): Promise<Described>
  /** The files the creator picks in the file dialog; none when they cancel. Only these may start a video. */
  chooseFiles(kind: 'footage' | 'assets' | 'music' | 'looks' | 'script'): Promise<string[]>
}
