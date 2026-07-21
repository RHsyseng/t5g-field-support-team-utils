/* global $, sessionStorage, bootstrap */ // eslint-disable-line no-redeclare

let currentAnalysisId = null
let currentCaseNumber = null
let showingRaw = false
let pollErrorCount = 0
let cachedCodeFindings = []
let cachedFindingCount = 0
const MAX_POLL_ERRORS = 5
const JIRA_SERVER = 'https://issues.redhat.com'
const VERSION_ALIGNMENT_RE = /indexed at|version alignment|customer on|may not match/i

$(document).ready(function () {
  $('#search-btn').click(searchCase)
  $('#case-number-input').keypress(function (e) {
    if (e.which === 13) searchCase()
  })
  $('#toggle-view-btn').click(toggleView)
  $('#reanalyze-btn').click(function () { triggerAnalysis(true) })
  $('#run-analysis-btn').click(function () { triggerAnalysis(false) })
  $('#feedback-up').click(function () { submitFeedback('up') })
  $('#feedback-down').click(function () { submitFeedback('down') })
  $('#code-findings-sort, #code-findings-repo-filter, #code-findings-query-filter').on('change', function () {
    renderCodeFindingsList()
  })
  $(document).on('click', '.similar-case-ref', function (e) {
    e.preventDefault()
    const caseNum = $(this).data('case')
    if (!caseNum) return
    $('#case-number-input').val(String(caseNum))
    searchCase()
  })

  // Check for ongoing analysis from previous session
  resumeOngoingAnalysis()

  // Support deep-link: /agent?case=03252981
  const params = new URLSearchParams(window.location.search)
  const caseParam = params.get('case')
  if (caseParam && !sessionStorage.getItem('activeAnalysis')) {
    $('#case-number-input').val(caseParam)
    searchCase()
  }
})

function showAlert (msg, type) {
  $('#agent-alert')
    .removeClass('d-none alert-danger alert-warning alert-info alert-success')
    .addClass('alert-' + type)
    .text(msg)
}

function hideAlert () {
  $('#agent-alert').addClass('d-none')
}

function searchCase () {
  const caseNum = $('#case-number-input').val().trim()
  if (!caseNum) return
  if (!/^[0-9]{8}$/.test(caseNum)) {
    showAlert('Case number must be exactly 8 digits (e.g. 03252981)', 'warning')
    return
  }
  currentCaseNumber = caseNum
  hideAlert()
  $('#report-container').addClass('d-none')
  $('#no-report').addClass('d-none')
  $('#analysis-progress').addClass('d-none')

  $.ajax({
    url: '/api/ai/report/case/' + encodeURIComponent(caseNum),
    method: 'GET',
    dataType: 'json',
    success: function (data) {
      renderReport(data)
    },
    error: function (xhr) {
      if (xhr.status === 404) {
        $('#no-report-case').text(caseNum)
        $('#no-report').removeClass('d-none')
      } else if (xhr.status === 502 || xhr.status === 504) {
        showAlert('AI Agents service is unreachable. Is it running?', 'warning')
      } else {
        showAlert('Error fetching report: ' + (xhr.responseJSON ? xhr.responseJSON.detail || xhr.responseJSON.error : xhr.statusText), 'danger')
      }
    }
  })
}

function renderReport (data) {
  currentAnalysisId = data.id
  const report = data.full_report || {}
  cachedCodeFindings = []
  cachedFindingCount = 0

  const statusBadge = $('#report-status-badge')
  statusBadge.text(data.status || 'unknown')
  statusBadge.attr('class', 'badge ' + statusBadgeClass(data.status))

  const confidence = (report.analysis || {}).confidence || 'unknown'
  const confBadge = $('#report-confidence-badge')
  confBadge.text('Confidence: ' + confidence)
  confBadge.attr('class', 'badge ' + confidenceBadgeClass(confidence))

  let meta = 'Case ' + data.case_number
  if (data.timestamp) meta += ' | ' + new Date(data.timestamp).toLocaleString()
  if (data.model_id) meta += ' | ' + data.model_id
  if (data.rounds_executed) meta += ' | ' + data.rounds_executed + ' round(s)'
  $('#report-meta').text(meta)

  $('#hypothesis-body').html(markdownToHtml((report.analysis || {}).root_cause_hypothesis || 'N/A'))

  renderDomainTags(report)
  renderRecommendations(report)
  renderSimilarCases(report)
  renderJiras(report)
  renderCaseResolution(report)
  renderEngineeringResolution(report)
  renderVersionAlignmentWarning(report)
  renderKB(report)
  renderQuestions(report)
  renderAgentSummaries(report)
  renderDegraded(report)
  renderWarnings(report)
  renderAttachments(report)
  renderValidation(data.must_gather_validation, data.sos_report_validation)

  $('#raw-json').text(JSON.stringify(data, null, 2))

  showingRaw = false
  $('#structured-view').removeClass('d-none')
  $('#raw-view').addClass('d-none')
  $('#toggle-view-btn').text('Raw JSON')

  $('#report-container').removeClass('d-none')
  $('#no-report').addClass('d-none')
  $('#analysis-progress').addClass('d-none')

  $('#feedback-status').text('')
  $('#feedback-up').prop('disabled', false).removeClass('btn-success').addClass('btn-outline-success')
  $('#feedback-down').prop('disabled', false).removeClass('btn-danger').addClass('btn-outline-danger')

  loadThinkingLog()
}

function renderDomainTags (report) {
  const tags = ((report.analysis || {}).domain_tags || [])
  if (tags.length === 0) {
    $('#domain-tags-card').addClass('d-none')
    return
  }
  $('#domain-tags-card').removeClass('d-none')
  const html = tags.map(function (t) {
    return '<span class="badge bg-secondary me-1">' + escapeHtml(t) + '</span>'
  }).join('')
  $('#domain-tags-body').html(html)
}

function renderRecommendations (report) {
  const recs = report.recommendations || []
  if (recs.length === 0) { $('#recommendations-card').addClass('d-none'); return }
  $('#recommendations-card').removeClass('d-none')
  const html = recs.map(function (r) {
    return '<tr><td>' + markdownToHtml(r.action) + '</td>' +
      '<td><code>' + escapeHtml(r.command || '') + '</code></td>' +
      '<td><span class="badge ' + riskBadgeClass(r.risk) + '">' + escapeHtml(r.risk || 'safe') + '</span></td></tr>'
  }).join('')
  $('#recommendations-tbody').html(html)
}

function renderSimilarCases (report) {
  const cases = report.similar_cases || []
  if (cases.length === 0) { $('#similar-cases-card').addClass('d-none'); return }
  $('#similar-cases-card').removeClass('d-none')
  const html = cases.map(function (c) {
    const caseLink = '<a href="https://access.redhat.com/support/cases/' + escapeHtml(c.case_number) + '" target="_blank">' + escapeHtml(c.case_number) + '</a>'
    return '<tr><td>' + caseLink + '</td>' +
      '<td>' + (c.similarity ? (c.similarity * 100).toFixed(0) + '%' : '') + '</td>' +
      '<td><span class="badge ' + relevanceBadgeClass(c.relevance) + '">' + escapeHtml(c.relevance || '') + '</span></td>' +
      '<td>' + markdownToHtml(c.resolution_summary || c.applicability || '') + '</td></tr>'
  }).join('')
  $('#similar-cases-tbody').html(html)
}

function renderJiras (report) {
  const jiras = report.engineering_jiras || []
  if (jiras.length === 0) { $('#jiras-card').addClass('d-none'); return }
  $('#jiras-card').removeClass('d-none')
  const html = jiras.map(function (j) {
    const keyHtml = j.url
      ? '<a href="' + escapeHtml(j.url) + '" target="_blank">' + escapeHtml(j.key) + '</a>'
      : escapeHtml(j.key)
    return '<tr><td>' + keyHtml + '</td>' +
      '<td>' + escapeHtml(j.summary) + '</td>' +
      '<td>' + escapeHtml(j.status) + '</td>' +
      '<td>' + escapeHtml(j.priority) + '</td>' +
      '<td>' + escapeHtml((j.fix_versions || []).join(', ')) + '</td></tr>'
  }).join('')
  $('#jiras-tbody').html(html)
}

function renderCaseResolution (report) {
  const resolution = report.case_resolution || null
  if (!resolution) {
    $('#case-resolution-card').addClass('d-none')
    return
  }
  $('#case-resolution-card').removeClass('d-none')

  const statusBadge = $('#case-resolution-status-badge')
  statusBadge.text(resolution.status || 'unknown')

  let badgeClass = 'bg-secondary'
  if (resolution.status === 'in_progress' || resolution.status === 'pending') badgeClass = 'bg-primary'
  else if (resolution.status === 'completed' || resolution.status === 'found') badgeClass = 'bg-success'
  statusBadge.attr('class', 'badge ms-2 ' + badgeClass)

  $('#case-resolution-message').text(resolution.message || 'No message')
  $('#code-findings-count').text(resolution.code_findings_count || 0)
  $('#proposed-fixes-count').text(resolution.proposed_fixes_count || 0)
}

function getCodeFindings (report) {
  const resolution = report.case_resolution || {}
  if (Array.isArray(resolution.code_findings) && resolution.code_findings.length > 0) {
    return resolution.code_findings
  }
  if (Array.isArray(report.code_findings) && report.code_findings.length > 0) {
    return report.code_findings
  }
  return []
}

function renderEngineeringResolution (report) {
  const resolution = report.case_resolution || {}
  const findings = getCodeFindings(report)
  const count = resolution.code_findings_count != null
    ? resolution.code_findings_count
    : findings.length
  const show = count > 0 || resolution.status === 'found' || findings.length > 0

  cachedCodeFindings = findings
  cachedFindingCount = count

  if (!show) {
    $('#engineering-resolution-card').addClass('d-none')
    return
  }

  $('#engineering-resolution-card').removeClass('d-none')

  const hasFindings = count > 0 || findings.length > 0 || resolution.status === 'found'
  const statusBadge = $('#eng-res-status-badge')
  statusBadge.text(hasFindings ? 'Code Findings' : 'No Code Findings')
  statusBadge.attr('class', 'badge ' + (hasFindings ? 'bg-success' : 'bg-secondary'))

  $('#eng-res-findings-pill').text(count + ' finding' + (count === 1 ? '' : 's'))

  const ctx = report.engineering_resolution_context || {}
  const corr = ctx.correlation_confidence || ''
  const corrBadge = $('#eng-res-correlation-badge')
  if (corr) {
    corrBadge.removeClass('d-none')
      .text('Correlation: ' + corr)
      .attr('class', 'badge ' + confidenceBadgeClass(corr))
  } else {
    corrBadge.addClass('d-none').text('')
  }

  renderEngineeringContext(ctx)
  populateCodeFindingFilters(findings)
  renderCodeFindingsList()
}

function renderEngineeringContext (ctx) {
  if (!ctx || (!ctx.components_searched && !ctx.jira_fix_status && !ctx.similar_case_refs && !ctx.correlation_confidence)) {
    $('#eng-res-context').addClass('d-none').html('')
    return
  }
  $('#eng-res-context').removeClass('d-none')

  let html = ''

  const components = ctx.components_searched || []
  if (components.length > 0) {
    html += '<div class="mb-2"><span class="text-muted small me-2">Components Searched</span>'
    html += components.map(function (c) {
      return '<span class="badge bg-light text-dark border me-1">' + escapeHtml(c) + '</span>'
    }).join('')
    html += '</div>'
  }

  if (ctx.jira_fix_status) {
    html += '<div class="mb-2"><span class="text-muted small me-2">Jira Fix Status</span>'
    html += '<span>' + linkJiraKeysInText(ctx.jira_fix_status) + '</span></div>'
  }

  const similar = ctx.similar_case_refs || []
  if (similar.length > 0) {
    html += '<div class="mb-2"><span class="text-muted small me-2">Similar Cases</span>'
    html += similar.map(function (ref) {
      const caseNum = String(ref).replace(/\D/g, '')
      if (caseNum.length === 8) {
        return '<a href="/agent?case=' + encodeURIComponent(caseNum) + '" class="badge bg-primary text-decoration-none me-1 similar-case-ref" data-case="' + escapeHtml(caseNum) + '">' + escapeHtml(String(ref)) + '</a>'
      }
      return '<span class="badge bg-secondary me-1">' + escapeHtml(String(ref)) + '</span>'
    }).join('')
    html += '</div>'
  }

  if (ctx.correlation_confidence) {
    html += '<div class="mb-0"><span class="text-muted small me-2">Overall Confidence</span>'
    html += '<span class="badge ' + confidenceBadgeClass(ctx.correlation_confidence) + '">' +
      escapeHtml(ctx.correlation_confidence) + '</span></div>'
  }

  $('#eng-res-context').html(html)
}

function populateCodeFindingFilters (findings) {
  const repos = []
  const queries = []
  findings.forEach(function (f) {
    if (f.repo && repos.indexOf(f.repo) === -1) repos.push(f.repo)
    if (f.query_used && queries.indexOf(f.query_used) === -1) queries.push(f.query_used)
  })
  repos.sort()
  queries.sort()

  const repoSelect = $('#code-findings-repo-filter')
  const querySelect = $('#code-findings-query-filter')
  const currentRepo = repoSelect.val() || ''
  const currentQuery = querySelect.val() || ''

  repoSelect.html('<option value="">All repos</option>' + repos.map(function (r) {
    return '<option value="' + escapeHtml(r) + '">' + escapeHtml(r) + '</option>'
  }).join(''))
  querySelect.html('<option value="">All queries</option>' + queries.map(function (q) {
    return '<option value="' + escapeHtml(q) + '">' + escapeHtml(q) + '</option>'
  }).join(''))

  if (repos.indexOf(currentRepo) !== -1) repoSelect.val(currentRepo)
  if (queries.indexOf(currentQuery) !== -1) querySelect.val(currentQuery)
}

function renderCodeFindingsList () {
  let findings = cachedCodeFindings.slice()
  const sortMode = $('#code-findings-sort').val() || 'confidence-desc'
  const repoFilter = $('#code-findings-repo-filter').val() || ''
  const queryFilter = $('#code-findings-query-filter').val() || ''

  if (repoFilter) {
    findings = findings.filter(function (f) { return f.repo === repoFilter })
  }
  if (queryFilter) {
    findings = findings.filter(function (f) { return f.query_used === queryFilter })
  }

  findings.sort(function (a, b) {
    if (sortMode === 'confidence-asc') {
      return (a.confidence || 0) - (b.confidence || 0)
    }
    if (sortMode === 'repo') {
      return String(a.repo || '').localeCompare(String(b.repo || '')) ||
        (b.confidence || 0) - (a.confidence || 0)
    }
    if (sortMode === 'query') {
      return String(a.query_used || '').localeCompare(String(b.query_used || '')) ||
        (b.confidence || 0) - (a.confidence || 0)
    }
    // confidence-desc (default)
    return (b.confidence || 0) - (a.confidence || 0)
  })

  if (findings.length === 0) {
    $('#code-findings-accordion').html('')
    if (cachedCodeFindings.length === 0) {
      $('#code-findings-filters').addClass('d-none')
      $('#code-findings-empty').addClass('d-none')
    } else {
      $('#code-findings-filters').removeClass('d-none')
      $('#code-findings-empty').removeClass('d-none')
    }
    return
  }

  $('#code-findings-filters').removeClass('d-none')
  $('#code-findings-empty').addClass('d-none')
  $('#code-findings-accordion').html(findings.map(function (f, idx) {
    return renderCodeFindingItem(f, idx)
  }).join(''))

  // Re-init tooltips for newly rendered elements
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('#code-findings-accordion [data-bs-toggle="tooltip"]'))
  tooltipTriggerList.forEach(function (el) {
    // eslint-disable-next-line no-new
    new bootstrap.Tooltip(el)
  })
}

function renderCodeFindingItem (finding, idx) {
  const conf = typeof finding.confidence === 'number' ? finding.confidence : 0
  const pct = Math.round(conf * 100)
  const confClass = numericConfidenceClass(conf)
  const collapseId = 'code-finding-' + idx
  const symbol = finding.symbol || finding.qualified_name || 'unknown'
  const repo = finding.repo || 'unknown'
  const filePath = finding.file_path || ''
  const locationHtml = buildCodeLocationHtml(finding, symbol, repo, filePath)
  const relevance = finding.relevance || ''
  const snippet = finding.snippet || ''
  const lang = detectSnippetLanguage(filePath, snippet)
  const callChain = finding.call_chain || []
  const histHint = finding.historical_fix_hint || ''
  const recency = finding.change_recency || ''
  const queryUsed = finding.query_used || ''

  let html = '<div class="accordion-item code-finding-item">'
  html += '<h2 class="accordion-header">'
  html += '<button class="accordion-button collapsed py-2" type="button" data-bs-toggle="collapse" data-bs-target="#' + collapseId + '">'
  html += '<div class="w-100 pe-3">'
  html += '<div class="d-flex flex-wrap align-items-center gap-2 mb-1">'
  html += '<strong>' + locationHtml + '</strong>'
  html += '<span class="badge ' + confClass + '">' + pct + '%</span>'
  html += '<div class="confidence-bar flex-grow-1" style="max-width:120px" title="Confidence ' + pct + '%">'
  html += '<div class="confidence-bar-fill ' + numericConfidenceBarClass(conf) + '" style="width:' + pct + '%"></div></div>'
  if (queryUsed) html += '<span class="badge bg-light text-dark border">' + escapeHtml(queryUsed) + '</span>'
  html += '</div>'
  if (relevance) {
    html += '<div class="small text-muted text-truncate">' + escapeHtml(relevance) + '</div>'
  }
  html += '</div></button></h2>'

  html += '<div id="' + collapseId + '" class="accordion-collapse collapse" data-bs-parent="#code-findings-accordion">'
  html += '<div class="accordion-body">'

  if (finding.qualified_name) {
    html += '<p class="small mb-2"><span class="text-muted">Qualified name:</span> <code>' +
      escapeHtml(finding.qualified_name) + '</code></p>'
  }

  if (relevance) {
    html += '<p class="mb-3">' + escapeHtml(relevance) + '</p>'
  }

  if (snippet) {
    html += '<pre class="code-snippet bg-light p-2 border rounded mb-3"><code class="language-' + lang + '">' +
      escapeHtml(snippet) + '</code></pre>'
  }

  if (callChain.length > 0) {
    html += '<div class="mb-3"><span class="text-muted small d-block mb-1">Call chain</span>'
    html += '<nav aria-label="Call chain" class="call-chain">'
    html += callChain.map(function (step, i) {
      const sep = i < callChain.length - 1 ? '<span class="call-chain-sep text-muted mx-1">→</span>' : ''
      return '<span class="badge bg-light text-dark border">' + escapeHtml(step) + '</span>' + sep
    }).join('')
    html += '</nav></div>'
  }

  if (histHint) {
    html += '<div class="mb-2"><span class="text-muted small me-2">Historical fix</span>'
    html += linkJiraKeysInText(histHint) + '</div>'
  }

  if (recency) {
    html += '<div class="mb-0"><span class="text-muted small me-2">Change recency</span>'
    html += '<span class="badge bg-warning text-dark" title="Recent commit activity">' +
      escapeHtml(recency) + '</span></div>'
  }

  html += '</div></div></div>'
  return html
}

function buildCodeLocationHtml (finding, symbol, repo, filePath) {
  const label = '<code>' + escapeHtml(symbol) + '</code> in <strong>' + escapeHtml(repo) + '</strong>' +
    (filePath ? ' at <code>' + escapeHtml(filePath) + '</code>' : '')
  const href = buildGitHubFileUrl(finding)
  if (href) {
    return '<a href="' + escapeHtml(href) + '" target="_blank" rel="noopener noreferrer" ' +
      'onclick="event.stopPropagation()">' + label + '</a>'
  }
  return label
}

function buildGitHubFileUrl (finding) {
  const direct = finding.git_url || finding.repo_url || finding.html_url
  if (!direct) return ''
  // Already a file/blob URL
  if (/\/blob\//.test(direct) || /\.(go|py|js|ts|java|rs|c|h)$/.test(direct)) {
    return direct
  }
  // Repo root + file path
  if (finding.file_path) {
    const base = direct.replace(/\.git$/, '').replace(/\/$/, '')
    const ref = finding.ref || finding.branch || 'main'
    return base + '/blob/' + ref + '/' + finding.file_path.replace(/^\//, '')
  }
  return direct
}

function detectSnippetLanguage (filePath, snippet) {
  const path = (filePath || '').toLowerCase()
  if (path.endsWith('.go')) return 'go'
  if (path.endsWith('.py')) return 'python'
  if (path.endsWith('.js') || path.endsWith('.ts')) return 'javascript'
  if (path.endsWith('.java')) return 'java'
  if (path.endsWith('.rs')) return 'rust'
  if (/^\s*package\s+\w+/.test(snippet || '') || /\bfunc\s+\w+\s*\(/.test(snippet || '')) return 'go'
  if (/^\s*(def|class|import)\s+/.test(snippet || '')) return 'python'
  return 'text'
}

function numericConfidenceClass (conf) {
  if (conf >= 0.75) return 'bg-success'
  if (conf >= 0.5) return 'bg-warning text-dark'
  return 'bg-danger'
}

function numericConfidenceBarClass (conf) {
  if (conf >= 0.75) return 'bg-success'
  if (conf >= 0.5) return 'bg-warning'
  return 'bg-danger'
}

function linkJiraKeysInText (text) {
  if (!text) return ''
  const escaped = escapeHtml(text)
  return escaped.replace(/\b((?:OCPBUGS|RHEL)-\d+)\b/g, function (match) {
    return '<a href="' + JIRA_SERVER + '/browse/' + match + '" target="_blank" rel="noopener noreferrer">' +
      match + '</a>'
  })
}

function renderVersionAlignmentWarning (report) {
  const messages = collectVersionAlignmentMessages(report)
  const banner = $('#version-alignment-banner')
  if (messages.length === 0) {
    banner.addClass('d-none').text('')
    return
  }
  banner.removeClass('d-none').html(
    '<strong>Version alignment:</strong> ' + escapeHtml(messages[0]) +
    (messages.length > 1
      ? '<ul class="mb-0 mt-2">' + messages.slice(1).map(function (m) {
        return '<li>' + escapeHtml(m) + '</li>'
      }).join('') + '</ul>'
      : '')
  )
}

function collectVersionAlignmentMessages (report) {
  const messages = []
  const seen = {}

  function add (msg) {
    if (!msg || seen[msg] || !VERSION_ALIGNMENT_RE.test(msg)) return
    seen[msg] = true
    messages.push(msg)
  }

  const resolution = report.case_resolution || {}
  add(resolution.message)
  add(resolution.version_alignment_warning)
  add(resolution.version_warning)

  const ctx = report.engineering_resolution_context || {}
  add(ctx.version_alignment_warning)
  add(ctx.version_warning)

  ;(report.context_warnings || []).forEach(add)
  ;(report.warnings || []).forEach(add)

  const summaries = report.agent_summaries || {}
  const cga = summaries.code_graph_agent || {}
  add(cga.key_finding)
  add(cga.skip_reason)
  add(cga.warning)

  return messages
}

function renderKB (report) {
  const refs = report.kb_references || []
  if (refs.length === 0) { $('#kb-card').addClass('d-none'); return }
  $('#kb-card').removeClass('d-none')
  const html = refs.map(function (r) {
    const titleHtml = r.url
      ? '<a href="' + escapeHtml(r.url) + '" target="_blank">' + escapeHtml(r.title) + '</a>'
      : escapeHtml(r.title)
    return '<tr><td>' + titleHtml + '</td>' +
      '<td>' + escapeHtml(r.doc_type || '') + '</td>' +
      '<td><small>' + escapeHtml(r.snippet || '') + '</small></td></tr>'
  }).join('')
  $('#kb-tbody').html(html)
}

function renderQuestions (report) {
  const qs = report.clarifying_questions || []
  if (qs.length === 0) { $('#questions-card').addClass('d-none'); return }
  $('#questions-card').removeClass('d-none')
  const html = qs.map(function (q) { return '<li>' + escapeHtml(q) + '</li>' }).join('')
  $('#questions-list').html(html)
}

function renderAgentSummaries (report) {
  const summaries = report.agent_summaries || {}
  const agents = report.agents_consulted || []
  if (agents.length === 0 && Object.keys(summaries).length === 0) {
    $('#agents-card').addClass('d-none')
    return
  }
  $('#agents-card').removeClass('d-none')
  let html = ''
  const keys = Object.keys(summaries).length > 0 ? Object.keys(summaries) : agents
  const findingCount = cachedFindingCount || getCodeFindings(report).length

  keys.forEach(function (name) {
    const s = summaries[name] || {}
    if (name === 'code_graph_agent') {
      html += renderCodeGraphAgentSummary(s, findingCount)
      return
    }
    html += '<div class="mb-2"><strong>' + escapeHtml(name) + '</strong>'
    if (s.status) html += ' <span class="badge bg-secondary">' + escapeHtml(s.status) + '</span>'
    if (s.confidence) html += ' <span class="badge bg-info">' + (s.confidence * 100).toFixed(0) + '%</span>'
    if (s.key_finding) html += '<br><small>' + escapeHtml(s.key_finding) + '</small>'
    html += '</div>'
  })
  $('#agents-body').html(html)

  const tooltipTriggerList = [].slice.call(document.querySelectorAll('#agents-body [data-bs-toggle="tooltip"]'))
  tooltipTriggerList.forEach(function (el) {
    // eslint-disable-next-line no-new
    new bootstrap.Tooltip(el)
  })
}

function renderCodeGraphAgentSummary (s, findingCount) {
  const status = s.status || ''
  const skipReason = s.skip_reason || s.key_finding || ''
  const count = findingCount || 0
  let html = '<div class="mb-2 agent-summary-row">'
  html += '<strong>code_graph_agent</strong>'
  if (status) {
    html += ' <span class="badge ' + agentStatusBadgeClass(status) + '">' + escapeHtml(status) + '</span>'
  }
  if (typeof s.confidence === 'number') {
    html += ' <span class="badge bg-info">' + (s.confidence * 100).toFixed(0) + '%</span>'
  }
  if (status === 'found_relevant' && count > 0) {
    html += ' <span class="badge bg-success">' + count + ' finding' +
      (count === 1 ? '' : 's') + '</span>'
  }
  if ((status === 'not_applicable' || status === 'unavailable') && skipReason) {
    html += ' <span class="text-muted small" data-bs-toggle="tooltip" data-bs-placement="top" title="' +
      escapeHtml(skipReason) + '">(skipped)</span>'
  } else if (s.key_finding) {
    html += '<br><small>' + escapeHtml(s.key_finding) + '</small>'
  }
  html += '</div>'
  return html
}

function agentStatusBadgeClass (status) {
  if (status === 'found_relevant') return 'bg-success'
  if (status === 'partial_match') return 'bg-warning text-dark'
  if (status === 'no_results') return 'bg-secondary'
  if (status === 'not_applicable' || status === 'unavailable') return 'bg-light text-dark border'
  return 'bg-secondary'
}

function renderDegraded (report) {
  const steps = report.degraded_steps || []
  if (steps.length === 0) { $('#degraded-card').addClass('d-none'); return }
  $('#degraded-card').removeClass('d-none')
  const html = steps.map(function (d) {
    return '<tr><td>' + escapeHtml(d.step) + '</td>' +
      '<td>' + escapeHtml(d.reason) + '</td>' +
      '<td>' + escapeHtml(d.impact) + '</td></tr>'
  }).join('')
  $('#degraded-tbody').html(html)
}

function renderWarnings (report) {
  const warns = report.context_warnings || []
  if (warns.length === 0) { $('#warnings-card').addClass('d-none'); return }
  $('#warnings-card').removeClass('d-none')
  const html = warns.map(function (w) { return '<li>' + escapeHtml(w) + '</li>' }).join('')
  $('#warnings-list').html(html)
}

function renderAttachments (report) {
  const atts = report.attachments_reviewed || []
  if (atts.length === 0) { $('#attachments-card').addClass('d-none'); return }
  $('#attachments-card').removeClass('d-none')
  const html = atts.map(function (a) {
    return '<tr><td>' + escapeHtml(a.file_name) + '</td>' +
      '<td>' + escapeHtml(a.file_type || '') + '</td>' +
      '<td>' + (a.size_kb || '') + '</td>' +
      '<td>' + escapeHtml(a.status || '') + '</td></tr>'
  }).join('')
  $('#attachments-tbody').html(html)
}

function renderValidation (mgValidation, sosValidation) {
  const mgActive = mgValidation && mgValidation.validated
  const sosActive = sosValidation && sosValidation.validated

  if (!mgActive && !sosActive) {
    $('#validation-card').addClass('d-none')
    return
  }
  $('#validation-card').removeClass('d-none')

  const primary = mgActive ? mgValidation : sosValidation
  let decisionClass = 'bg-secondary'
  if (primary.decision === 'confirmed') decisionClass = 'bg-success'
  else if (primary.decision === 'refuted') decisionClass = 'bg-danger'
  else if (primary.decision === 'inconclusive') decisionClass = 'bg-warning text-dark'

  let html = '<div class="mb-3">'
  html += '<span class="badge ' + decisionClass + ' me-2">' + escapeHtml(primary.decision) + '</span>'
  if (primary.confidence != null) {
    html += '<span class="badge bg-info me-2">Confidence: ' + (primary.confidence * 100).toFixed(0) + '%</span>'
  }
  if (primary.round) {
    html += '<span class="badge bg-secondary">Round ' + primary.round + '</span>'
  }
  html += '</div>'

  if (primary.reasoning) {
    html += '<p>' + markdownToHtml(primary.reasoning) + '</p>'
  }

  let cmdIndex = 0

  if (mgActive) {
    const mgCmds = mgValidation.commands_executed || []
    if (mgCmds.length > 0) {
      html += '<h6 class="mt-3">Must-Gather Commands'
      if (mgValidation.filename) {
        html += ' <small class="text-muted">(' + escapeHtml(mgValidation.filename)
        if (mgValidation.size_mb) html += ', ' + mgValidation.size_mb.toFixed(1) + ' MB'
        html += ')</small>'
      }
      html += '</h6>'
      html += _renderCommandAccordion(mgCmds, 'mg', cmdIndex)
      cmdIndex += mgCmds.length
    }
  }

  if (sosActive) {
    const sosCmds = sosValidation.commands_executed || []
    if (sosCmds.length > 0) {
      html += '<h6 class="mt-3">Sos-Report Commands'
      if (sosValidation.filename) {
        html += ' <small class="text-muted">(' + escapeHtml(sosValidation.filename)
        if (sosValidation.size_mb) html += ', ' + sosValidation.size_mb.toFixed(1) + ' MB'
        html += ')</small>'
      }
      html += '</h6>'
      html += _renderCommandAccordion(sosCmds, 'sos', cmdIndex)
    }
  }

  $('#validation-body').html(html)
}

function _renderCommandAccordion (cmds, prefix, startIdx) {
  let html = '<div class="accordion mb-2" id="val-' + prefix + '-accordion">'
  cmds.forEach(function (cmd, idx) {
    let statusIcon = '?'
    let statusClass = 'text-secondary'
    if (cmd.status === 'success') {
      statusIcon = '✓'; statusClass = 'text-success'
    } else if (cmd.status === 'empty') {
      statusIcon = '○'; statusClass = 'text-muted'
    } else if (cmd.status === 'timeout') {
      statusIcon = '⏱'; statusClass = 'text-warning'
    } else if (cmd.status === 'error' || cmd.status === 'omc_error') {
      statusIcon = '✗'; statusClass = 'text-danger'
    }

    const cmdText = cmd.command || cmd.original_command || 'N/A'
    const collapseId = 'val-' + prefix + '-cmd-' + (startIdx + idx)

    html += '<div class="accordion-item">'
    html += '<h2 class="accordion-header">'
    html += '<button class="accordion-button collapsed py-2" type="button" data-bs-toggle="collapse" data-bs-target="#' + collapseId + '">'
    html += '<span class="' + statusClass + ' me-2">' + statusIcon + '</span> '
    html += '<code class="me-2">' + escapeHtml(cmdText) + '</code> '
    if (cmd.duration_ms) html += '<small class="text-muted">' + cmd.duration_ms + 'ms</small>'
    html += '</button></h2>'
    html += '<div id="' + collapseId + '" class="accordion-collapse collapse">'
    html += '<div class="accordion-body">'
    if (cmd.stdout) {
      html += '<pre class="bg-light p-2 border rounded" style="max-height:300px;overflow:auto;font-size:0.85em">' + escapeHtml(cmd.stdout) + '</pre>'
    } else {
      html += '<p class="text-muted">(no output)</p>'
    }
    if (cmd.stderr) {
      html += '<pre class="bg-light p-2 border rounded text-danger" style="max-height:150px;overflow:auto;font-size:0.85em">' + escapeHtml(cmd.stderr) + '</pre>'
    }
    html += '</div></div></div>'
  })
  html += '</div>'
  return html
}

function toggleView () {
  showingRaw = !showingRaw
  if (showingRaw) {
    $('#structured-view').addClass('d-none')
    $('#raw-view').removeClass('d-none')
    $('#toggle-view-btn').text('Structured View')
  } else {
    $('#structured-view').removeClass('d-none')
    $('#raw-view').addClass('d-none')
    $('#toggle-view-btn').text('Raw JSON')
  }
}

function triggerAnalysis (force) {
  if (!currentCaseNumber) return
  hideAlert()
  pollErrorCount = 0
  $('#no-report').addClass('d-none')
  $('#report-container').addClass('d-none')
  $('#analysis-progress').removeClass('d-none')
  $('#analysis-status-text').text('Queuing analysis...')

  let url = '/api/ai/analyze/' + encodeURIComponent(currentCaseNumber)
  if (force) url += '?force=true'

  $.ajax({
    url,
    method: 'POST',
    dataType: 'json',
    success: function (data) {
      if (data.task_id) {
        $('#analysis-status-text').text('Task queued. Polling for completion...')
        // Save to sessionStorage for resume on page reload
        sessionStorage.setItem('activeAnalysis', JSON.stringify({
          task_id: data.task_id,
          case_number: currentCaseNumber,
          started_at: Date.now()
        }))
        pollStatus(data.task_id)
      }
    },
    error: function (xhr) {
      $('#analysis-progress').addClass('d-none')
      if (xhr.status === 502 || xhr.status === 504) {
        showAlert('AI Agents service is unreachable. Is it running?', 'warning')
      } else {
        showAlert('Failed to start analysis: ' + (xhr.responseJSON ? xhr.responseJSON.detail || xhr.responseJSON.error : xhr.statusText), 'danger')
      }
    }
  })
}

function pollStatus (taskId) {
  $.ajax({
    url: '/api/ai/status/' + encodeURIComponent(taskId),
    method: 'GET',
    dataType: 'json',
    success: function (data) {
      pollErrorCount = 0
      let statusText = 'State: ' + data.state
      if (data.state === 'PENDING') {
        statusText = 'Queued, waiting for worker...'
      } else if (data.state === 'STARTED') {
        statusText = 'Running AI analysis...'
      }
      $('#analysis-status-text').text(statusText)

      if (data.state === 'SUCCESS') {
        sessionStorage.removeItem('activeAnalysis')
        $('#analysis-progress').addClass('d-none')
        searchCase()
      } else if (data.state === 'FAILURE') {
        sessionStorage.removeItem('activeAnalysis')
        $('#analysis-progress').addClass('d-none')
        showAlert('Analysis failed: ' + (data.error || 'Unknown error'), 'danger')
      } else {
        setTimeout(function () { pollStatus(taskId) }, 3000)
      }
    },
    error: function () {
      pollErrorCount++
      if (pollErrorCount >= MAX_POLL_ERRORS) {
        pollErrorCount = 0
        sessionStorage.removeItem('activeAnalysis')
        $('#analysis-progress').addClass('d-none')
        showAlert('Lost contact with analysis task after multiple retries. Please run a new analysis.', 'warning')
      } else {
        $('#analysis-status-text').text('Connection issue, retrying... (' + pollErrorCount + '/' + MAX_POLL_ERRORS + ')')
        setTimeout(function () { pollStatus(taskId) }, 5000)
      }
    }
  })
}

function loadThinkingLog () {
  if (!currentAnalysisId) return
  $('#thinking-log-tbody').html('<tr><td colspan="7" class="text-center">Loading...</td></tr>')
  $('#code-graph-timeline-btn').addClass('d-none')
  $('#code-graph-timeline').html('')
  $('#code-graph-timeline-empty').addClass('d-none')

  $.ajax({
    url: '/api/ai/logs/' + encodeURIComponent(currentAnalysisId),
    method: 'GET',
    dataType: 'json',
    success: function (logs) {
      if (!logs || logs.length === 0) {
        $('#thinking-log-tbody').html('<tr><td colspan="7" class="text-muted text-center">No log entries</td></tr>')
        return
      }
      const html = logs.map(function (l) {
        const round = l.round !== undefined ? l.round : (l.step_number !== undefined ? l.step_number : '')
        const tokensIn = l.input_tokens != null ? formatNumber(l.input_tokens) : ''
        const tokensOut = l.output_tokens != null ? formatNumber(l.output_tokens) : ''
        const tokensInClass = l.input_tokens != null ? '' : 'text-muted'
        const tokensOutClass = l.output_tokens != null ? '' : 'text-muted'
        const rowClass = l.agent_name === 'code_graph_agent' ? ' class="table-light"' : ''

        return '<tr' + rowClass + '><td>' + round + '</td>' +
          '<td>' + escapeHtml(l.agent_name || '') + '</td>' +
          '<td><span class="badge ' + thinkingActionBadgeClass(l.action_type) + '">' +
          escapeHtml(l.action_type || '') + '</span></td>' +
          '<td><small>' + escapeHtml(l.detail || '') + '</small></td>' +
          '<td>' + (l.duration_ms != null ? l.duration_ms + 'ms' : '') + '</td>' +
          '<td class="' + tokensInClass + '">' + tokensIn + '</td>' +
          '<td class="' + tokensOutClass + '">' + tokensOut + '</td></tr>'
      }).join('')
      $('#thinking-log-tbody').html(html)
      renderCodeGraphTimeline(logs)
    },
    error: function () {
      $('#thinking-log-tbody').html('<tr><td colspan="7" class="text-muted text-center">Could not load thinking log</td></tr>')
    }
  })
}

function renderCodeGraphTimeline (logs) {
  const entries = (logs || []).filter(function (l) {
    return l.agent_name === 'code_graph_agent'
  })
  if (entries.length === 0) {
    $('#code-graph-timeline-btn').addClass('d-none')
    return
  }
  $('#code-graph-timeline-btn').removeClass('d-none')
  $('#code-graph-timeline-empty').addClass('d-none')

  const html = entries.map(function (l) {
    const action = l.action_type || 'STEP'
    let itemClass = 'timeline-item'
    if (action === 'VERSION_ALIGNMENT_WARNING' || action === 'DEGRADED') itemClass += ' timeline-warn'
    else if (action === 'SKIP') itemClass += ' timeline-skip'
    else if (action === 'CBM_QUERY') itemClass += ' timeline-query'

    let item = '<li class="' + itemClass + '">'
    item += '<div class="d-flex flex-wrap align-items-center gap-2">'
    item += '<span class="badge ' + thinkingActionBadgeClass(action) + '">' + escapeHtml(action) + '</span>'
    if (l.duration_ms != null) {
      item += '<small class="text-muted">' + l.duration_ms + 'ms</small>'
    }
    item += '</div>'
    if (l.detail) {
      item += '<div class="small mt-1">' + escapeHtml(l.detail) + '</div>'
    }
    item += '</li>'
    return item
  }).join('')
  $('#code-graph-timeline').html(html)
}

function thinkingActionBadgeClass (actionType) {
  const action = (actionType || '').toUpperCase()
  if (action === 'CBM_QUERY') return 'bg-primary'
  if (action === 'RESOLVE') return 'bg-info text-dark'
  if (action === 'REFORMULATE') return 'bg-secondary'
  if (action === 'BUDGET') return 'bg-dark'
  if (action === 'VERSION_ALIGNMENT_WARNING') return 'bg-warning text-dark'
  if (action === 'DEGRADED') return 'bg-warning text-dark'
  if (action === 'SKIP') return 'bg-light text-dark border'
  return 'bg-secondary'
}

function formatNumber (num) {
  if (num == null) return ''
  return num.toLocaleString()
}

function submitFeedback (vote) {
  if (!currentAnalysisId) return

  $.ajax({
    url: '/api/ai/feedback/' + encodeURIComponent(currentAnalysisId),
    method: 'POST',
    contentType: 'application/json',
    data: JSON.stringify({ vote }),
    dataType: 'json',
    success: function () {
      $('#feedback-status').text('Feedback submitted!')
      if (vote === 'up') {
        $('#feedback-up').removeClass('btn-outline-success').addClass('btn-success')
      } else {
        $('#feedback-down').removeClass('btn-outline-danger').addClass('btn-danger')
      }
      $('#feedback-up').prop('disabled', true)
      $('#feedback-down').prop('disabled', true)
    },
    error: function () {
      $('#feedback-status').text('Failed to submit feedback')
    }
  })
}

function resumeOngoingAnalysis () {
  const stored = sessionStorage.getItem('activeAnalysis')
  if (!stored) return

  try {
    const data = JSON.parse(stored)
    const ageHours = (Date.now() - data.started_at) / (1000 * 60 * 60)

    // Ignore if older than 2 hours (likely expired)
    if (ageHours > 2) {
      sessionStorage.removeItem('activeAnalysis')
      return
    }

    // Resume the analysis
    currentCaseNumber = data.case_number
    $('#case-number-input').val(data.case_number)
    $('#no-report').addClass('d-none')
    $('#report-container').addClass('d-none')
    $('#analysis-progress').removeClass('d-none')
    $('#analysis-status-text').text('Resuming analysis...')

    // Start polling
    pollStatus(data.task_id)
  } catch (e) {
    // Invalid JSON, clear it
    sessionStorage.removeItem('activeAnalysis')
  }
}

function statusBadgeClass (status) {
  if (status === 'complete') return 'bg-success'
  if (status === 'partial') return 'bg-warning text-dark'
  if (status === 'failed') return 'bg-danger'
  return 'bg-secondary'
}

function confidenceBadgeClass (confidence) {
  if (confidence === 'high') return 'bg-success'
  if (confidence === 'medium') return 'bg-warning text-dark'
  if (confidence === 'low') return 'bg-danger'
  return 'bg-secondary'
}

function riskBadgeClass (risk) {
  if (risk === 'safe') return 'bg-success'
  if (risk === 'write') return 'bg-warning text-dark'
  if (risk === 'destructive') return 'bg-danger'
  return 'bg-secondary'
}

function relevanceBadgeClass (relevance) {
  if (relevance === 'high') return 'bg-success'
  if (relevance === 'medium') return 'bg-warning text-dark'
  if (relevance === 'low') return 'bg-info'
  return 'bg-secondary'
}

function escapeHtml (str) {
  if (!str) return ''
  const div = document.createElement('div')
  div.appendChild(document.createTextNode(str))
  return div.innerHTML
}

function markdownToHtml (markdown) {
  if (!markdown) return ''

  // Escape HTML first
  let html = escapeHtml(markdown)

  // Convert markdown to HTML
  // Bold **text**
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  // Italic *text*
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')
  // Code `code`
  html = html.replace(/`(.+?)`/g, '<code>$1</code>')
  // Line breaks
  html = html.replace(/\n/g, '<br>')

  // Headers
  html = html.replace(/^### (.+)$/gm, '<h5>$1</h5>')
  html = html.replace(/^## (.+)$/gm, '<h4>$1</h4>')
  html = html.replace(/^# (.+)$/gm, '<h3>$1</h3>')

  // Bullet lists (simple version)
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>')
  html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')

  return html
}
