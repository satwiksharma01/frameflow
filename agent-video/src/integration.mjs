// The Frameflow developer can consume these contracts without running the CLI.
export { validateBrief, validateInputs, validateTimings, validateStoryboard, checkFrameflowFiles } from './frameflow.mjs';
export { analyzeReference, validateReferenceAnalysis, referenceRequest } from './reference-evidence.mjs';
export { prepareReference, checkReference, exportFrameflow, sampleReference } from './reference.mjs';

export const integrationVersion = 1;
