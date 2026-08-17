import React, { useState } from 'react'
import { Mail, Send, CheckCircle2, AlertCircle } from 'lucide-react'

const FORM_ENDPOINT = 'https://formspree.io/f/xrpzyggb'

export default function ContactPage() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [status, setStatus] = useState('idle') // idle | sending | success | error

  const handleSubmit = async (e) => {
    e.preventDefault()
    setStatus('sending')
    try {
      const res = await fetch(FORM_ENDPOINT, {
        method: 'POST',
        headers: { Accept: 'application/json' },
        body: new FormData(e.target),
      })
      if (res.status === 200) {
        setStatus('success')
        setName('')
        setEmail('')
        setMessage('')
      } else {
        setStatus('error')
      }
    } catch {
      setStatus('error')
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.panel}>
        <div style={styles.panelHeader}>
          <Mail size={18} color="#B8860B" />
          <span style={styles.panelTitle}>צור קשר</span>
        </div>

        {status === 'success' ? (
          <div style={styles.successBox}>
            <CheckCircle2 size={40} color="#2E7D32" />
            <p style={styles.successText}>ההודעה נשלחה בהצלחה, תודה!</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} style={styles.form}>
            <label style={styles.label}>
              שם
              <input
                type="text"
                name="name"
                value={name}
                onChange={e => setName(e.target.value)}
                required
                style={styles.input}
                dir="rtl"
              />
            </label>

            <label style={styles.label}>
              דוא"ל
              <input
                type="email"
                name="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                style={styles.input}
                dir="rtl"
              />
            </label>

            <label style={styles.label}>
              הודעה
              <textarea
                name="message"
                value={message}
                onChange={e => setMessage(e.target.value)}
                required
                rows={6}
                style={styles.textarea}
                dir="rtl"
              />
            </label>

            {status === 'error' && (
              <div style={styles.errorBox}>
                <AlertCircle size={16} color="#8B1A1A" />
                <span>אירעה שגיאה בשליחת ההודעה. נסו שוב.</span>
              </div>
            )}

            <button type="submit" style={{ ...styles.submitBtn, opacity: status === 'sending' ? 0.7 : 1 }} disabled={status === 'sending'}>
              {status === 'sending'
                ? <span style={styles.spinnerInline} />
                : <Send size={15} style={{ marginLeft: 6 }} />}
              {status === 'sending' ? 'שולח…' : 'שליחה'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

const styles = {
  page: { padding: '32px 0 60px', maxWidth: 560, margin: '0 auto' },
  panel: {
    background: '#FDFBF7',
    border: '1px solid rgba(184,134,11,.2)',
    borderRadius: 12,
    padding: '24px 28px',
    boxShadow: '0 2px 12px rgba(28,22,16,.07)',
  },
  panelHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 20,
  },
  panelTitle: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '1.15rem',
    fontWeight: 600,
    color: '#1C1610',
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
  },
  label: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    fontFamily: "'Heebo', sans-serif",
    fontSize: '.85rem',
    color: '#6B5E47',
  },
  input: {
    padding: '10px 14px',
    border: '1.5px solid #D4C5A0',
    borderRadius: 8,
    fontFamily: "'Heebo', sans-serif",
    fontSize: '.9rem',
    background: '#FDFBF7',
    color: '#1C1610',
    outline: 'none',
  },
  textarea: {
    padding: '10px 14px',
    border: '1.5px solid #D4C5A0',
    borderRadius: 8,
    fontFamily: "'Heebo', sans-serif",
    fontSize: '.9rem',
    background: '#FDFBF7',
    color: '#1C1610',
    outline: 'none',
    resize: 'vertical',
  },
  submitBtn: {
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
    justifyContent: 'center',
    whiteSpace: 'nowrap',
    boxShadow: '0 2px 8px rgba(14,36,64,.3)',
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
  errorBox: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    background: 'rgba(139,26,26,.08)',
    border: '1px solid rgba(139,26,26,.25)',
    borderRadius: 8,
    padding: '10px 14px',
    color: '#8B1A1A',
    fontSize: '.85rem',
    fontFamily: "'Heebo', sans-serif",
  },
  successBox: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 12,
    padding: '40px 0',
  },
  successText: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '1.05rem',
    color: '#1C1610',
  },
}
