// Lightweight debug logger.
// Enable with either:
//   - URL: add ?debug=1 to the address bar
//   - Console: localStorage.setItem('debug', '1') then reload
// Disable: localStorage.removeItem('debug') (or drop ?debug=1) then reload.

function computeEnabled() {
  if (typeof window === 'undefined') return false
  try {
    if (new URLSearchParams(window.location.search).get('debug') === '1') {
      localStorage.setItem('debug', '1')
      return true
    }
    return localStorage.getItem('debug') === '1'
  } catch {
    return false
  }
}

export const DEBUG_ENABLED = computeEnabled()

export function dlog(scope, ...args) {
  if (!DEBUG_ENABLED) return
  console.log(`%c[${scope}]`, 'color:#B8860B;font-weight:600', ...args)
}
