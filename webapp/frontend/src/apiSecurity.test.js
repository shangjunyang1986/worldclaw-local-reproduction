import assert from 'node:assert/strict'
import test from 'node:test'

import { authorizationHeaders, resolveApiToken, tokenizedUrl } from './apiSecurity.js'

test('URL token takes precedence and authorization headers preserve content type', () => {
  assert.equal(resolveApiToken('?job=abc&token=url-secret', 'stored-secret'), 'url-secret')
  const headers = authorizationHeaders('url-secret', { 'Content-Type': 'application/json' })
  assert.equal(headers.get('authorization'), 'Bearer url-secret')
  assert.equal(headers.get('content-type'), 'application/json')
})

test('tokenizedUrl supports EventSource query authentication', () => {
  assert.equal(tokenizedUrl('/api/jobs/abc/logs?tail=1', 'safe token'), '/api/jobs/abc/logs?tail=1&token=safe+token')
  assert.equal(tokenizedUrl('/api/health', ''), '/api/health')
})

