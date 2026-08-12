import { useState, useEffect, useRef } from 'react'

const DEFAULT_BATCH = 24

// Reveals `items` incrementally instead of rendering all of them at once.
// The data itself is already fully loaded client-side (see useVideos.js)
// — this only controls how many DOM nodes (VideoCards) get MOUNTED,
// since mounting hundreds/thousands of cards at once (e.g. הלכה יומית's
// 1300+ videos) is what actually causes the visible lag when switching
// category, not the network fetch itself. More of `items` is revealed
// automatically as the returned `sentinelRef` element scrolls into view
// — render it as an empty element right after the grid.
export function useInfiniteReveal(items, batchSize = DEFAULT_BATCH) {
  const [count, setCount] = useState(batchSize)
  const sentinelRef = useRef(null)

  // Reset back to the first batch whenever the underlying list itself
  // changes (new search, category switch, filter change) — otherwise
  // switching from a long list to a short/different one would either
  // keep `count` pinned uselessly high, or continue revealing a
  // completely unrelated list from where the old one left off.
  useEffect(() => {
    setCount(batchSize)
  }, [items, batchSize])

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          setCount(c => Math.min(c + batchSize, items.length))
        }
      },
      { rootMargin: '600px' } // start revealing well before the sentinel is actually visible
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [items.length, batchSize])

  return {
    visibleItems: items.slice(0, count),
    sentinelRef,
    hasMore: count < items.length,
  }
}
