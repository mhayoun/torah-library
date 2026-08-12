import { useCallback, useRef, useState } from 'react'

// Debounce delay before firing the request — CategoryPage calls this on
// every keystroke (no explicit "search" button there, unlike SearchPage),
// so without this every character typed would fire its own request.
const DEBOUNCE_MS = 300

// Below this length a query is almost always a false start (still
// typing the first word) — searching that early would burn a request
// per keystroke for no useful result, so we just wait for more input.
const MIN_QUERY_LENGTH = 3

// Full-text search over the extracted PDF/DOCX handout content (see
// backend/doc_text_utils.py + GET /api/search-docs). Shared between
// SearchPage and CategoryPage so both pages behave identically instead
// of maintaining two copies of this fetch/debounce logic.
export function useDocSearch() {
  const [docResults, setDocResults] = useState([])
  const [docSearchLoading, setDocSearchLoading] = useState(false)
  const [docSearched, setDocSearched] = useState(false)
  const timerRef = useRef(null)
  const requestIdRef = useRef(0)

  const runDocSearch = useCallback((rawQuery, { debounce = false } = {}) => {
    clearTimeout(timerRef.current)
    const q = (rawQuery || '').trim()

    if (q.length < MIN_QUERY_LENGTH) {
      ++requestIdRef.current // invalidate any in-flight request from a longer query typed then deleted
      setDocResults([])
      setDocSearchLoading(false)
      setDocSearched(false)
      return
    }

    const fire = () => {
      const thisRequestId = ++requestIdRef.current
      setDocSearchLoading(true)
      fetch(`/api/search-docs?q=${encodeURIComponent(q)}`)
        .then(r => {
          if (!r.ok) throw new Error(`Erreur serveur : ${r.status}`)
          return r.json()
        })
        .then(data => {
          if (thisRequestId !== requestIdRef.current) return // a newer search superseded this one
          setDocResults(Array.isArray(data.results) ? data.results : [])
        })
        .catch(() => {
          if (thisRequestId === requestIdRef.current) setDocResults([])
        })
        .finally(() => {
          if (thisRequestId === requestIdRef.current) {
            setDocSearchLoading(false)
            setDocSearched(true)
          }
        })
    }

    if (debounce) {
      timerRef.current = setTimeout(fire, DEBOUNCE_MS)
    } else {
      fire()
    }
  }, [])

  return { docResults, docSearchLoading, docSearched, runDocSearch }
}
