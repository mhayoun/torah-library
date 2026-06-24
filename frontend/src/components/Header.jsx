import React, { useState } from 'react'
import { Search, BookOpen, Menu, X } from 'lucide-react'

const NAV_ITEMS = [
  { key: 'כל הקטגוריות', label: 'כל הקטגוריות' },
  { key: 'דעת ותורה',    label: 'דעת ותורה' },
  { key: 'הליכות עולם',  label: 'הליכות עולם' },
  { key: 'הלכה יומית',   label: 'הלכה יומית' },
  { key: 'השיעור השבועי', label: 'השיעור השבועי' },
  { key: 'שיחת חולין', label: 'שיחת חולין' },
  { key: '__search__',   label: 'חיפוש', icon: Search },
]

export default function Header({ activeTab, onTabChange }) {
  const [mobileOpen, setMobileOpen] = useState(false)

  const handleTab = (key) => {
    onTabChange(key)
    setMobileOpen(false)
  }

  return (
    <header style={styles.header}>
      <div style={styles.inner}>
        {/* Logo */}
        <div style={styles.logo} onClick={() => handleTab('כל הקטגוריות')}>
          <div style={styles.logoIcon}>
            <BookOpen size={22} color="#F5F0E8" strokeWidth={1.5} />
          </div>
          <div>
            <div style={styles.logoTitle}>מאגר שיעורי תורה</div>
            <div style={styles.logoSub}>ספריית שיעורים</div>
          </div>
        </div>

        {/* Desktop nav */}
        <nav style={styles.nav}>
          {NAV_ITEMS.map(item => {
            const Icon = item.icon
            const isActive = activeTab === item.key
            return (
              <button
                key={item.key}
                style={{ ...styles.navBtn, ...(isActive ? styles.navBtnActive : {}) }}
                onClick={() => handleTab(item.key)}
              >
                {Icon && <Icon size={14} style={{ marginLeft: 4 }} />}
                {item.label}
              </button>
            )
          })}
        </nav>

        {/* Mobile hamburger */}
        <button style={styles.hamburger} onClick={() => setMobileOpen(o => !o)}>
          {mobileOpen ? <X size={22} color="#F5F0E8" /> : <Menu size={22} color="#F5F0E8" />}
        </button>
      </div>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div style={styles.mobileMenu}>
          {NAV_ITEMS.map(item => {
            const Icon = item.icon
            const isActive = activeTab === item.key
            return (
              <button
                key={item.key}
                style={{ ...styles.mobileBtn, ...(isActive ? styles.mobileBtnActive : {}) }}
                onClick={() => handleTab(item.key)}
              >
                {Icon && <Icon size={14} style={{ marginLeft: 6 }} />}
                {item.label}
              </button>
            )
          })}
        </div>
      )}
    </header>
  )
}

const styles = {
  header: {
    background: 'linear-gradient(135deg, #1A3A5C 0%, #0E2440 100%)',
    boxShadow: '0 2px 16px rgba(0,0,0,.3)',
    position: 'sticky',
    top: 0,
    zIndex: 100,
  },
  inner: {
    maxWidth: 1200,
    margin: '0 auto',
    padding: '0 24px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    height: 68,
    gap: 24,
  },
  logo: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    cursor: 'pointer',
    flexShrink: 0,
  },
  logoIcon: {
    width: 40,
    height: 40,
    borderRadius: '50%',
    background: 'rgba(184,134,11,.25)',
    border: '1.5px solid rgba(212,160,23,.5)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoTitle: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '1.05rem',
    fontWeight: 700,
    color: '#F5F0E8',
    lineHeight: 1.1,
  },
  logoSub: {
    fontSize: '.68rem',
    color: '#B8860B',
    letterSpacing: '.05em',
    marginTop: 1,
  },
  nav: {
    display: 'flex',
    gap: 4,
    flexWrap: 'wrap',
    justifyContent: 'flex-end',
  },
  navBtn: {
    background: 'none',
    border: 'none',
    color: 'rgba(245,240,232,.75)',
    fontSize: '.82rem',
    fontFamily: "'Heebo', sans-serif",
    fontWeight: 400,
    padding: '6px 12px',
    borderRadius: 4,
    display: 'flex',
    alignItems: 'center',
    transition: 'all .15s',
    whiteSpace: 'nowrap',
  },
  navBtnActive: {
    background: 'rgba(184,134,11,.25)',
    color: '#D4A017',
    fontWeight: 600,
    border: '1px solid rgba(184,134,11,.4)',
  },
  hamburger: {
    background: 'none',
    border: 'none',
    display: 'none',
    padding: 6,
  },
  mobileMenu: {
    background: '#0E2440',
    padding: '8px 24px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
  },
  mobileBtn: {
    background: 'none',
    border: 'none',
    color: 'rgba(245,240,232,.8)',
    fontFamily: "'Heebo', sans-serif",
    fontSize: '.9rem',
    textAlign: 'right',
    padding: '10px 8px',
    borderRadius: 4,
    display: 'flex',
    alignItems: 'center',
    borderBottom: '1px solid rgba(255,255,255,.06)',
  },
  mobileBtnActive: {
    color: '#D4A017',
    background: 'rgba(184,134,11,.15)',
  },
}
