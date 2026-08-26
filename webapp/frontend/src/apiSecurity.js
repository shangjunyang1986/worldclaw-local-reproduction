export function resolveApiToken(search, stored = '') {
  const value = new URLSearchParams(search || '').get('token')
  return (value || stored || '').trim()
}

export function authorizationHeaders(token, initial) {
  const headers = new Headers(initial || {})
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return headers
}

export function tokenizedUrl(url, token) {
  if (!token) return url
  const parsed = new URL(url, 'http://worldclaw.local')
  parsed.searchParams.set('token', token)
  return parsed.origin === 'http://worldclaw.local'
    ? `${parsed.pathname}${parsed.search}${parsed.hash}`
    : parsed.href
}

