import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// jsdom has no layout engine; Ant Design observes real elements in the browser.
class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
Object.defineProperty(window, 'ResizeObserver', { value: TestResizeObserver, writable: true })
const nativeComputedStyle = window.getComputedStyle.bind(window)
window.getComputedStyle = (element) => nativeComputedStyle(element)

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})
