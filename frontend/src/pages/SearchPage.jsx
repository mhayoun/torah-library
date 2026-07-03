import React, { useState, useMemo, useCallback, useEffect } from 'react'
import { Search, Filter, SlidersHorizontal } from 'lucide-react'
import VideoCard from '../components/VideoCard.jsx'
import { dlog } from '../utils/debug.js'

const ALL_LABEL = 'כל הקטגוריות'
const ALL_YEARS = 'כל השנים'

export default function SearchPage({ allVideos, categories, years, keywords = [], initialParams }) {
  const [query, setQuery]       = useState(initialParams?.query || '')
  const [category, setCategory] = useState(initialParams?.category || ALL_LABEL)
  const [year, setYear]         = useState(initialParams?.year || ALL_YEARS)
  const [searched, setSearched] = useState(false)
  const [loading, setLoading]   = useState(false)

  // If the person arrived here via the HomePage quick-search bar, run the
  // search immediately with the params they picked there.
  // NOTE: no extra "already applied" ref-guard here on purpose — React 18
  // StrictMode runs effects twice in dev (mount → cleanup → mount again),
  // and a ref guard would mark itself "done" on the throwaway first run,
  // then skip re-arming the timer on the real second run, leaving the
  // spinner stuck forever. Relying only on the [initialParams] dependency
  // array is Strict-Mode-safe: cleanup cancels the first timer, the second
  // run schedules a fresh one, and it fires normally.
  useEffect(() => {
    if (!initialParams) return
    dlog('SearchPage', 'initialParams effect firing', initialParams)
    setQuery(initialParams.query || '')
    setCategory(initialParams.category || ALL_LABEL)
    setYear(initialParams.year || ALL_YEARS)
    setLoading(true)
    setSearched(false)
    const t = setTimeout(() => {
      dlog('SearchPage', 'initialParams search complete')
      setSearched(true)
      setLoading(false)
    }, 400)
    return () => {
      dlog('SearchPage', 'initialParams effect cleanup (clearing timer)')
      clearTimeout(t)
    }
  }, [initialParams])

  const results = useMemo(() => {
    if (!searched) return []
    const q = query.trim()
    const r = allVideos
      .map(v => {
        // Topics (keyword + start position) only exist on הלכה יומית videos
        // that have been processed by the backend's transcript pipeline.
        // A "topic match" is what lets us jump straight into the video at
        // the moment that subject is discussed, instead of just finding
        // the video by its title.
        const topicMatches = (q && Array.isArray(v.topics))
          ? v.topics.filter(t => t.keyword && t.keyword.includes(q))
          : []

        const matchQuery = !q ||
          v.title?.includes(q) ||
          v.playlist?.includes(q) ||
          v.category?.includes(q) ||
          topicMatches.length > 0
        const matchCat  = category === ALL_LABEL || v.category === category
        const matchYear = year === ALL_YEARS || v.hebraic_year === year

        if (!matchQuery || !matchCat || !matchYear) return null
        return { video: v, topicMatches }
      })
      .filter(Boolean)
    dlog('SearchPage', 'results computed', { query, category, year, count: r.length })
    return r
  }, [allVideos, query, category, year, searched])

  const topicMatchCount = useMemo(
    () => results.filter(r => r.topicMatches.length > 0).length,
    [results]
  )

  const handleSearch = useCallback(() => {
    dlog('SearchPage', 'manual search button clicked', { query, category, year })
    setLoading(true)
    setSearched(false)
    setTimeout(() => {
      setSearched(true)
      setLoading(false)
    }, 400)
  }, [query, category, year])

  const handleKey = (e) => { if (e.key === 'Enter') handleSearch() }

  return (
    <div style={styles.page}>
      {/* Search panel */}
      <div style={styles.panel}>
        <div style={styles.panelHeader}>
          <SlidersHorizontal size={18} color="#B8860B" />
          <span style={styles.panelTitle}>חיפוש שיעורים</span>
        </div>

        <div style={styles.controls}>
          {/* Text search */}
          <div style={styles.inputWrap}>
            <Search size={16} style={styles.inputIcon} />
            <input
              type="text"
              placeholder="חיפוש לפי כותרת או לפי נושא בתוך השיעור…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={handleKey}
              style={styles.input}
              dir="rtl"
              list="keyword-suggestions"
              autoComplete="off"
            />
            {/* Native listbox of every distinct topic keyword the backend
                extracted from the transcripts (fetched via /api/keywords,
                see useKeywords.js) — lets people pick a known subject
                instead of guessing free text. */}
            <datalist id="keyword-suggestions">
              {keywords.map(k => <option key={k} value={k} />)}
            </datalist>
          </div>

          {/* Category select */}
          <div style={styles.selectWrap}>
            <Filter size={14} style={styles.selectIcon} />
            <select
              value={category}
              onChange={e => setCategory(e.target.value)}
              style={styles.select}
            >
              <option value={ALL_LABEL}>{ALL_LABEL}</option>
              {categories.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          {/* Year listbox */}
          <div style={styles.selectWrap}>
            <select
              value={year}
              onChange={e => setYear(e.target.value)}
              style={styles.select}
            >
              <option value={ALL_YEARS}>{ALL_YEARS}</option>
              {years.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>

          <button style={{ ...styles.searchBtn, opacity: loading ? 0.7 : 1 }} onClick={handleSearch} disabled={loading}>
            {loading
              ? <span style={styles.spinnerInline} />
              : <Search size={15} style={{ marginLeft: 6 }} />}
            {loading ? 'מחפש…' : 'חפש'}
          </button>
        </div>
      </div>

      {/* Spinner */}
      {loading && (
        <div style={styles.spinnerWrap}>
          <div style={styles.spinner} />
          <p style={styles.spinnerText}>מחפש שיעורים…</p>
        </div>
      )}

      {/* Results */}
      {!loading && !searched && (
        <div style={styles.empty}>
          <div style={styles.emptyIcon}>🔍</div>
          <p style={styles.emptyText}>הגדירו פרמטרים לחיפוש ולחצו על "חפש"</p>
        </div>
      )}

      {!loading && searched && results.length === 0 && (
        <div style={styles.empty}>
          <div style={styles.emptyIcon}>📜</div>
          <p style={styles.emptyText}>לא נמצאו תוצאות. נסו מילות חיפוש אחרות.</p>
        </div>
      )}

      {!loading && results.length > 0 && (
        <>
          <div style={styles.resultsHeader}>
            <span style={styles.resultCount}>
              {results.length} שיעורים נמצאו
              {topicMatchCount > 0 && (
                <span style={styles.resultSub}>
                  {' '}· {topicMatchCount} מתוכם לפי נושא בתוך השיעור
                </span>
              )}
            </span>
          </div>
          <div style={styles.grid}>
            {results.map(({ video, topicMatches }) => (
              <VideoCard key={video.id} video={video} matchedTopics={topicMatches} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

const styles = {
  page: { padding: '32px 0 60px' },
  panel: {
    background: '#FDFBF7',
    border: '1px solid rgba(184,134,11,.2)',
    borderRadius: 12,
    padding: '20px 24px',
    marginBottom: 32,
    boxShadow: '0 2px 12px rgba(28,22,16,.07)',
  },
  panelHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 16,
  },
  panelTitle: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '1.05rem',
    fontWeight: 600,
    color: '#1C1610',
  },
  controls: {
    display: 'flex',
    gap: 12,
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  inputWrap: {
    position: 'relative',
    flex: '1 1 240px',
  },
  inputIcon: {
    position: 'absolute',
    right: 12,
    top: '50%',
    transform: 'translateY(-50%)',
    color: '#6B5E47',
    pointerEvents: 'none',
  },
  input: {
    width: '100%',
    padding: '10px 38px 10px 14px',
    border: '1.5px solid #D4C5A0',
    borderRadius: 8,
    fontFamily: "'Heebo', sans-serif",
    fontSize: '.9rem',
    background: '#FDFBF7',
    color: '#1C1610',
    outline: 'none',
    direction: 'rtl',
  },
  selectWrap: {
    position: 'relative',
    flex: '0 1 180px',
  },
  selectIcon: {
    position: 'absolute',
    right: 10,
    top: '50%',
    transform: 'translateY(-50%)',
    color: '#6B5E47',
    pointerEvents: 'none',
  },
  select: {
    width: '100%',
    padding: '10px 32px 10px 14px',
    border: '1.5px solid #D4C5A0',
    borderRadius: 8,
    fontFamily: "'Heebo', sans-serif",
    fontSize: '.88rem',
    background: '#FDFBF7',
    color: '#1C1610',
    direction: 'rtl',
    appearance: 'none',
    cursor: 'pointer',
    outline: 'none',
  },
  searchBtn: {
    background: 'linear-gradient(135deg, #1A3A5C, #0E2440)',
    color: '#F5F0E8',
    border: 'none',
    borderRadius: 8,
    padding: '10px 24px',
    fontFamily: "'Heebo', sans-serif",
    fontSize: '.9rem',
    fontWeight: 600,
    display: 'flex',
    alignItems: 'center',
    whiteSpace: 'nowrap',
    boxShadow: '0 2px 8px rgba(14,36,64,.3)',
    flexShrink: 0,
  },
  empty: {
    textAlign: 'center',
    padding: '80px 24px',
    color: '#6B5E47',
  },
  emptyIcon: { fontSize: '3rem', marginBottom: 16 },
  emptyText: { fontSize: '1rem', fontFamily: "'Frank Ruhl Libre', serif" },
  resultsHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 20,
    padding: '0 4px',
  },
  resultCount: {
    fontSize: '.85rem',
    color: '#6B5E47',
    fontFamily: "'Heebo', sans-serif",
  },
  resultSub: {
    color: '#B8860B',
    fontWeight: 600,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
    gap: 20,
  },
  spinnerWrap: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '80px 24px',
    gap: 16,
  },
  spinner: {
    width: 44,
    height: 44,
    border: '4px solid rgba(184,134,11,.2)',
    borderTop: '4px solid #B8860B',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
  spinnerText: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '1rem',
    color: '#6B5E47',
  },
  spinnerInline: {
    display: 'inline-block',
    width: 14,
    height: 14,
    border: '2px solid rgba(245,240,232,.4)',
    borderTop: '2px solid #F5F0E8',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
    marginLeft: 6,
  },
}
