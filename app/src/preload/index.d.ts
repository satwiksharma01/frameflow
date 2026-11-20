import type { FrameflowApi } from '../shared/types'

declare global {
  interface Window {
    frameflow: FrameflowApi
  }
}
