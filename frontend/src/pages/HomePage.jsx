import React from 'react'
import { BookOpen, ChevronLeft } from 'lucide-react'

const CATEGORY_ICONS = {
  'דעת ותורה':   '📖',
  'הליכות עולם': '🌍',
  'הלכה יומית':  '⚖️',
  'השיעור השבועי': '📅',
  'שיחת חולין': '🎙️',
}

export default function HomePage({ catalog, onCategorySelect }) {
  const entries = Object.entries(catalog)
  const totalVideos = entries.reduce((sum, [, videos]) => sum + videos.length, 0)

  return (
    <div style={styles.page}>
      {/* Hero */}
      <div style={styles.hero}>
        <div style={styles.heroIcon}>
          <BookOpen size={40} color="#D4A017" strokeWidth={1.2} />
        </div>
        <h1 style={styles.heroTitle}>מאגר שיעורי תורה</h1>
        <p style={styles.heroSub}>ספריית שיעורים מקוונת — לימוד תורה בכל זמן ובכל מקום</p>
        <div style={styles.heroStats}>
          <div style={styles.stat}>
            <span style={styles.statNum}>{entries.length}</span>
            <span style={styles.statLabel}>קטגוריות</span>
          </div>
          <div style={styles.statDiv} />
          <div style={styles.stat}>
            <span style={styles.statNum}>{totalVideos}</span>
            <span style={styles.statLabel}>שיעורים</span>
          </div>
        </div>
      </div>

      {/* Category cards */}
      <div style={styles.grid}>
        {entries.map(([catName, videos]) => (
          <button
            key={catName}
            style={styles.catCard}
            onClick={() => onCategorySelect(catName)}
          >
            <div style={styles.catIcon}>{CATEGORY_ICONS[catName] || '📚'}</div>
            <div style={styles.catInfo}>
              <h3 style={styles.catName}>{catName}</h3>
              <p style={styles.catCount}>{videos.length} שיעורים</p>
            </div>
            <ChevronLeft size={16} color="#B8860B" style={{ marginRight: 'auto', flexShrink: 0 }} />
          </button>
        ))}
      </div>
    </div>
  )
}

const styles = {
  page: { padding: '40px 0 60px' },
  hero: {
    textAlign: 'center',
    marginBottom: 48,
    padding: '40px 20px',
    background: 'linear-gradient(135deg, rgba(26,58,92,.06) 0%, rgba(184,134,11,.06) 100%)',
    borderRadius: 16,
    border: '1px solid rgba(184,134,11,.15)',
  },
  heroIcon: {
    width: 72,
    height: 72,
    borderRadius: '50%',
    background: 'linear-gradient(135deg, #1A3A5C, #0E2440)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    margin: '0 auto 16px',
    boxShadow: '0 4px 20px rgba(26,58,92,.3)',
  },
  heroTitle: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '2.2rem',
    fontWeight: 900,
    color: '#1C1610',
    marginBottom: 10,
  },
  heroSub: {
    fontSize: '.95rem',
    color: '#6B5E47',
    maxWidth: 440,
    margin: '0 auto 24px',
    lineHeight: 1.6,
  },
  heroStats: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 20,
    background: 'rgba(184,134,11,.1)',
    border: '1px solid rgba(184,134,11,.25)',
    borderRadius: 50,
    padding: '10px 28px',
  },
  stat: { textAlign: 'center' },
  statNum: {
    display: 'block',
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '1.4rem',
    fontWeight: 700,
    color: '#1A3A5C',
  },
  statLabel: { fontSize: '.72rem', color: '#6B5E47' },
  statDiv: { width: 1, height: 32, background: 'rgba(184,134,11,.3)' },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
    gap: 16,
  },
  catCard: {
    background: '#FDFBF7',
    border: '1.5px solid rgba(184,134,11,.18)',
    borderRadius: 12,
    padding: '18px 20px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: 14,
    textAlign: 'right',
    transition: 'all .2s',
    boxShadow: '0 2px 8px rgba(28,22,16,.06)',
  },
  catIcon: { fontSize: '1.8rem', flexShrink: 0 },
  catInfo: { flex: 1, minWidth: 0 },
  catName: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '1rem',
    fontWeight: 700,
    color: '#1C1610',
    marginBottom: 4,
  },
  catCount: { fontSize: '.75rem', color: '#6B5E47' },
}
