import '@testing-library/jest-dom'

// jsdom has no EventSource — stub a no-op so components that open an SSE
// stream on mount (e.g. the onboarding wizard's first-run poll) don't crash
// tests that render far enough to reach them.
class MockEventSource {
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  constructor(_url: string, _init?: EventSourceInit) {}
  close() {}
}
// @ts-expect-error — partial stub, sufficient for components that only use onmessage/close
globalThis.EventSource = MockEventSource
