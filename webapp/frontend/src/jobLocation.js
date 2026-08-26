export function jobIdFromSearch(search = '') {
  return new URLSearchParams(search).get('job') || null
}

export function jobSelectionPath(href, jobId) {
  const url = new URL(href)
  if (jobId) url.searchParams.set('job', String(jobId))
  else url.searchParams.delete('job')
  return `${url.pathname}${url.search}${url.hash}`
}
