/* global $, sessionStorage */ // eslint-disable-line no-redeclare

let currentAnalysisId = null
let currentCaseNumber = null
let showingRaw = false
let pollErrorCount = 0
const MAX_POLL_ERRORS = 5

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

  // Check for ongoing analysis from previous session
  resumeOngoingAnalysis()
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
  keys.forEach(function (name) {
    const s = summaries[name] || {}
    html += '<div class="mb-2"><strong>' + escapeHtml(name) + '</strong>'
    if (s.status) html += ' <span class="badge bg-secondary">' + escapeHtml(s.status) + '</span>'
    if (s.confidence) html += ' <span class="badge bg-info">' + (s.confidence * 100).toFixed(0) + '%</span>'
    if (s.key_finding) html += '<br><small>' + escapeHtml(s.key_finding) + '</small>'
    html += '</div>'
  })
  $('#agents-body').html(html)
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

        return '<tr><td>' + round + '</td>' +
          '<td>' + escapeHtml(l.agent_name || '') + '</td>' +
          '<td><span class="badge bg-secondary">' + escapeHtml(l.action_type || '') + '</span></td>' +
          '<td><small>' + escapeHtml(l.detail || '') + '</small></td>' +
          '<td>' + (l.duration_ms != null ? l.duration_ms + 'ms' : '') + '</td>' +
          '<td class="' + tokensInClass + '">' + tokensIn + '</td>' +
          '<td class="' + tokensOutClass + '">' + tokensOut + '</td></tr>'
      }).join('')
      $('#thinking-log-tbody').html(html)
    },
    error: function () {
      $('#thinking-log-tbody').html('<tr><td colspan="7" class="text-muted text-center">Could not load thinking log</td></tr>')
    }
  })
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
