import { useState, useEffect, useMemo } from 'react'

const API_URL  = '/api/cours'
const STALE_MS = 6 * 60 * 60 * 1000  // 6h — same TTL as Redis

// ── Session cache (survives page navigation, cleared on tab close) ─────────
function getCached() {
  try {
    const raw = sessionStorage.getItem('cours_cache')
    if (!raw) return null
    const { data, ts } = JSON.parse(raw)
    if (Date.now() - ts > STALE_MS) return null
    return data
  } catch { return null }
}

function setCache(data) {
  try {
    sessionStorage.setItem('cours_cache', JSON.stringify({ data, ts: Date.now() }))
  } catch {}
}

// ── Hook ──────────────────────────────────────────────────────────────────
export function useVideos() {
  const [catalog,  setCatalog]  = useState(null)
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)
  const [lastSync, setLastSync] = useState(null)
  const [total,    setTotal]    = useState(0)
  const [newCount, setNewCount] = useState(0)

  useEffect(() => {
    // 1. Try session cache first — instant response
    const cached = getCached()
    if (cached) {
      setCatalog(cached.catalog)
      setLastSync(cached.last_sync)
      setTotal(cached.total  ?? 0)
      setNewCount(cached.new ?? 0)
      setLoading(false)
      return
    }

    // 2. Otherwise hit the API backend
    fetch(API_URL)
      .then(r => {
        if (!r.ok) throw new Error(`Erreur serveur : ${r.status}`)
        return r.json()
      })
      .then(data => {
        // Backend returns { catalog, total, new, last_sync }
        setCatalog(data.catalog)
        setLastSync(data.last_sync)
        setTotal(data.total  ?? 0)
        setNewCount(data.new ?? 0)
        setCache(data)
        setLoading(false)
      })
      .catch(e => {
        setError(e.message)
        setLoading(false)
      })
  }, [])

  // Flat list of all videos with their category injected
  const allVideos = useMemo(() => {
    if (!catalog) return []
    return Object.entries(catalog).flatMap(([category, videos]) =>
      videos.map(v => ({ ...v, category }))
    )
  }, [catalog])

  // All unique years parsed from video titles + upload dates
  const years = useMemo(() => {
    const hebrewYearRe = /תש[פצ](?:"[א-ת]|[׳']?[א-ת]?)/g
    const yearSet = new Set()

    allVideos.forEach(v => {
      const gm = v.title?.match(/\b(20\d{2})\b/)
      if (gm) yearSet.add(gm[1])

      const hm = v.title?.match(hebrewYearRe)
      if (hm) hm.forEach(y => yearSet.add(y))

      if (v.upload_date) {
        const uy = new Date(v.upload_date).getFullYear()
        if (!isNaN(uy)) yearSet.add(String(uy))
      }
    })

    return Array.from(yearSet).sort().reverse()
  }, [allVideos])

  const categories = catalog ? Object.keys(catalog) : []

  return { catalog, allVideos, categories, years, loading, error, lastSync, total, newCount }
}
