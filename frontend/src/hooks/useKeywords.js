import { useState, useEffect } from 'react'

const API_URL  = '/api/keywords'
const STALE_MS = 6 * 60 * 60 * 1000  // 6h — same TTL policy as the cours cache

// ── Session cache (survives page navigation, cleared on tab close) ─────────
function getCached() {
  try {
    const raw = sessionStorage.getItem('keywords_cache')
    if (!raw) return null
    const { data, ts } = JSON.parse(raw)
    if (Date.now() - ts > STALE_MS) return null
    return data
  } catch { return null }
}

function setCache(data) {
  try {
    sessionStorage.setItem('keywords_cache', JSON.stringify({ data, ts: Date.now() }))
  } catch {}
}

// ── Hook ──────────────────────────────────────────────────────────────────
// Fetches the distinct, sorted list of AI-extracted topic keywords that
// the backend prepares and caches in Redis (keywords_list). Used to fill
// the datalist/listbox under the "חיפוש לפי..." search input, so people
// can pick a known keyword instead of typing free text.
export function useKeywords() {
  const [keywords, setKeywords] = useState(() => getCached() || [])
  const [loading, setLoading]   = useState(() => !getCached())
  const [error, setError]       = useState(null)

  useEffect(() => {
    if (getCached()) return  // already hydrated from session cache above

    fetch(API_URL)
      .then(r => {
        if (!r.ok) throw new Error(`Erreur serveur : ${r.status}`)
        return r.json()
      })
      .then(data => {
        const list = Array.isArray(data.keywords) ? data.keywords : []
        setKeywords(list)
        setCache(list)
        setLoading(false)
      })
      .catch(e => {
        setError(e.message)
        setLoading(false)
      })
  }, [])

  return { keywords, loading, error }
}
