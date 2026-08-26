import assert from 'node:assert/strict'
import test from 'node:test'

import { jobIdFromSearch, jobSelectionPath } from './jobLocation.js'

test('jobIdFromSearch reads a deep-linked job id', () => {
  assert.equal(jobIdFromSearch('?job=hok5v5s42'), 'hok5v5s42')
  assert.equal(jobIdFromSearch('?filter=active&job=job%20with%20spaces'), 'job with spaces')
  assert.equal(jobIdFromSearch('?job='), null)
  assert.equal(jobIdFromSearch(''), null)
})

test('jobSelectionPath sets the selected job and preserves other URL state', () => {
  assert.equal(
    jobSelectionPath('http://localhost/studio?filter=active&job=old#files', 'hok5v5s42'),
    '/studio?filter=active&job=hok5v5s42#files',
  )
})

test('jobSelectionPath clears only the job query parameter', () => {
  assert.equal(
    jobSelectionPath('http://localhost/studio?filter=active&job=hok5v5s42#files', null),
    '/studio?filter=active#files',
  )
})
