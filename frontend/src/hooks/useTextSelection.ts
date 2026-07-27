import { useState, useEffect, useRef } from 'react'
import type { Highlight } from '../types'

export interface PendingSelection {
  selectedText: string
  prefixContext: string
  suffixContext: string
  /** Viewport coords of the selection rectangle */
  position: { x: number; top: number; bottom: number }
}

/** Get selected text + surrounding context from within a container element. */
export function getSelectionContext(container: HTMLElement): PendingSelection | null {
  const sel = window.getSelection()
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null

  const range = sel.getRangeAt(0)
  const selectedText = sel.toString().trim()
  if (!selectedText || selectedText.length < 3) return null

  if (!container.contains(range.commonAncestorContainer)) return null

  const fullText = container.textContent || ''
  const idx = fullText.indexOf(selectedText)
  const prefixContext = idx >= 0 ? fullText.slice(Math.max(0, idx - 20), idx) : ''
  const suffixContext = idx >= 0 ? fullText.slice(idx + selectedText.length, idx + selectedText.length + 20) : ''

  const rect = range.getBoundingClientRect()
  return {
    selectedText,
    prefixContext,
    suffixContext,
    position: { x: rect.left + rect.width / 2, top: rect.top, bottom: rect.bottom },
  }
}

/**
 * Find the first index of `search` in `html` that is in text content (not inside a tag).
 * Prevents matching inside href="..." or other attributes.
 */
export function findInTextContent(html: string, search: string, startFrom = 0): number {
  let idx = startFrom
  while (true) {
    const found = html.indexOf(search, idx)
    if (found === -1) return -1
    // Is this inside a tag? Check if the last '<' before `found` has no closing '>' before `found`.
    const before = html.slice(0, found)
    const lastOpen = before.lastIndexOf('<')
    const lastClose = before.lastIndexOf('>')
    if (lastOpen <= lastClose) return found   // in text content ✓
    idx = found + 1                           // inside a tag — skip
  }
}

/** Safely inject <mark> tags into HTML, only matching text content (never inside tag attributes). */
export function applyHighlights(html: string, highlights: Highlight[]): string {
  if (!highlights.length) return html

  let result = html

  for (const h of highlights) {
    if (result.includes(`data-hid="${h.id}"`)) continue

    const text = h.selected_text
    const markOpen = `<mark data-hid="${h.id}" class="highlight-${h.color}">`
    const markClose = `</mark>`

    let matchIdx = -1

    // Try with prefix context (more specific — avoids wrong occurrence)
    if (h.prefix_context) {
      const prefix = h.prefix_context.slice(-8)
      const prefixIdx = findInTextContent(result, prefix)
      if (prefixIdx >= 0) {
        matchIdx = findInTextContent(result, text, prefixIdx + prefix.length - 2)
      }
    }

    // Fallback: first occurrence in text content
    if (matchIdx === -1) matchIdx = findInTextContent(result, text)

    if (matchIdx >= 0) {
      result = result.slice(0, matchIdx) + markOpen + text + markClose + result.slice(matchIdx + text.length)
    }
  }

  return result
}

export function useTextSelection(articleHighlights: Highlight[]) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [pendingSelection, setPendingSelection] = useState<PendingSelection | null>(null)
  const [editingHighlight, setEditingHighlight] = useState<{ highlight: Highlight; position: { x: number; top: number; bottom: number } } | null>(null)
  const [noteTooltip, setNoteTooltip] = useState<{ note: string; x: number; y: number } | null>(null)
  
  const articleHighlightsRef = useRef<Highlight[]>([])
  articleHighlightsRef.current = articleHighlights

  // Detect text selection for highlighting
  useEffect(() => {
    const handleMouseUp = () => {
      const container = containerRef.current
      if (!container) return
      const ctx = getSelectionContext(container)
      if (ctx) setPendingSelection(ctx)
    }
    document.addEventListener('mouseup', handleMouseUp)
    document.addEventListener('touchend', handleMouseUp)
    return () => {
      document.removeEventListener('mouseup', handleMouseUp)
      document.removeEventListener('touchend', handleMouseUp)
    }
  }, [])

  // Click to edit highlight
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const handleClick = (e: MouseEvent) => {
      const mark = (e.target as HTMLElement).closest('mark[data-hid]') as HTMLElement | null
      if (!mark) { setEditingHighlight(null); return }
      const hid = parseInt(mark.getAttribute('data-hid') || '0', 10)
      const h = articleHighlightsRef.current.find(h => h.id === hid)
      if (!h) return
      const rect = mark.getBoundingClientRect()
      setEditingHighlight({
        highlight: h,
        position: { x: rect.left + rect.width / 2, top: rect.top, bottom: rect.bottom },
      })
      setPendingSelection(null)
    }

    container.addEventListener('click', handleClick)
    return () => container.removeEventListener('click', handleClick)
  }, [])

  // Note tooltip on highlight hover
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const handleMouseOver = (e: MouseEvent) => {
      const mark = (e.target as HTMLElement).closest('mark[data-hid]') as HTMLElement | null
      if (!mark) { setNoteTooltip(null); return }
      const hid = parseInt(mark.getAttribute('data-hid') || '0', 10)
      const h = articleHighlightsRef.current.find(h => h.id === hid)
      if (!h?.note) { setNoteTooltip(null); return }
      const rect = mark.getBoundingClientRect()
      setNoteTooltip({ note: h.note, x: rect.left + rect.width / 2, y: rect.top })
    }

    const handleMouseLeave = () => setNoteTooltip(null)

    container.addEventListener('mouseover', handleMouseOver)
    container.addEventListener('mouseleave', handleMouseLeave)
    return () => {
      container.removeEventListener('mouseover', handleMouseOver)
      container.removeEventListener('mouseleave', handleMouseLeave)
    }
  }, [])

  return {
    containerRef,
    pendingSelection,
    setPendingSelection,
    editingHighlight,
    setEditingHighlight,
    noteTooltip,
    setNoteTooltip
  }
}
