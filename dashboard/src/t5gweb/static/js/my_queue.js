// My Queue DataTable initialization
/* globals $, marked, DOMPurify */ // eslint-disable-line no-redeclare

/**
 * HTML-escape a plain-text string for safe insertion into innerHTML.
 * @param {string} text - untrusted plain text
 * @returns {string} escaped text
 */
function escapeHtml (text) {
  if (text === null || text === undefined) return ''
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/**
 * Sanitize an HTML string before it is injected via innerHTML. Comment content
 * is authored by customers / external parties, so it must be sanitized to
 * prevent stored/DOM XSS. Falls back to HTML-escaping (never raw injection) if
 * DOMPurify is not loaded.
 * @param {string} htmlStr - untrusted HTML
 * @returns {string} sanitized HTML
 */
function sanitizeHtml (htmlStr) {
  if (!htmlStr) return ''
  if (typeof DOMPurify !== 'undefined') {
    return DOMPurify.sanitize(htmlStr)
  }
  return escapeHtml(htmlStr)
}

/**
 * Render a Markdown string to sanitized HTML. Portal comment bodies are stored
 * as Markdown (converted from the portal's HTML server-side); render them with
 * marked and run the result through DOMPurify. Falls back to escaped text if
 * marked is not loaded.
 * @param {string} text - Markdown source (untrusted)
 * @returns {string} sanitized HTML string
 */
function renderMarkdown (text) {
  if (!text) return ''
  if (typeof marked !== 'undefined') {
    return sanitizeHtml(marked.parse(text))
  }
  return escapeHtml(text)
}

/**
 * Format child row content with two-column layout for portal and JIRA comments
 * @param {object} data - Case data containing portal_comments and jira_comments arrays
 * @returns {string} HTML string for child row
 */
function format (data) {
  let result = '<div class=\'card p-3\'>'
  result += '<div class=\'row\'>'

  // Left column - Portal comments (60% width)
  result += '<div class=\'col-md-7\'>'
  result += '<h4>Portal Comments</h4>'
  if (data.portal_comments && data.portal_comments.length > 0) {
    result += '<div style=\'max-height: 400px; overflow-y: auto;\'>'
    for (let i = 0; i < data.portal_comments.length; i++) {
      const comment = data.portal_comments[i]
      const commentType = comment.comment_type || ''
      const typeLabel = commentType
      let borderColor = '#6c757d'
      if (commentType === 'Customer') {
        borderColor = 'rgb(0, 103, 187)'
      } else if (commentType === 'Associate') {
        borderColor = 'rgb(187, 0, 0)'
      } else if (commentType === 'Bug') {
        borderColor = 'rgb(120, 0, 187)'
      } else if (commentType === 'Partner') {
        borderColor = 'rgb(0, 150, 100)'
      }

      result += '<div class=\'mb-3 p-2\' style=\'border-left: 3px solid ' + borderColor + ';\'>'
      // Private (internal, not customer-visible) comments are labeled, not
      // hidden - matches the reference dashboards. Default/missing = public.
      const privateBadge = comment.is_public === false
        ? ' <span class=\'badge bg-warning text-dark\'>🔒 Private</span>'
        : ''
      result += '<div class=\'fw-bold\'>' + escapeHtml(comment.author || 'Unknown') +
        (typeLabel ? ' <span class=\'fw-normal text-muted\'>(' + escapeHtml(typeLabel) + ')</span>' : '') +
        privateBadge + '</div>'
      result += '<div class=\'text-muted small\'>' +
        (comment.date ? escapeHtml(comment.date.substring(0, 19).replace('T', ' ')) : 'No date') + '</div>'
      result += '<div class=\'mt-2\'>' + renderMarkdown(comment.body) + '</div>'
      result += '</div>'
    }
    result += '</div>'
  } else {
    result += '<p class=\'text-muted\'>No portal comments</p>'
  }
  result += '</div>'

  // Right column - JIRA comments (40% width)
  result += '<div class=\'col-md-5\'>'
  result += '<h4>JIRA Comments</h4>'
  if (data.jira_comments && data.jira_comments.length > 0) {
    result += '<div style=\'max-height: 400px; overflow-y: auto;\'>'
    for (let i = 0; i < data.jira_comments.length; i++) {
      const comment = data.jira_comments[i]
      result += '<div class=\'mb-3 p-2 border-start border-3 border-success\'>'
      result += '<div class=\'fw-bold\'>' + escapeHtml(comment.author || 'Unknown') + '</div>'
      result += '<div class=\'text-muted small\'>' +
        (comment.updated ? escapeHtml(comment.updated.substring(0, 19).replace('T', ' ')) : 'No date') + '</div>'
      result += '<div class=\'mt-2\'>' + sanitizeHtml(comment.body) + '</div>'
      result += '</div>'
    }
    result += '</div>'
  } else {
    result += '<p class=\'text-muted\'>No JIRA comments</p>'
  }
  result += '</div>'

  result += '</div></div>'
  return result
}

// Initialize DataTable
$(document).ready(function () {
  const tableElement = $('#my-queue-data')
  if (tableElement.length === 0) {
    console.error('My Queue table #my-queue-data not found')
    return
  }

  // Guard against a header/body column-count mismatch (a template bug). Skip
  // for an empty queue, which legitimately has no body cells (DataTables shows
  // its own "no data" message).
  const bodyRowCount = tableElement.find('tbody tr').length
  const headerCount = tableElement.find('thead tr th').length
  const firstRowColCount = tableElement.find('tbody tr:first td').length
  if (bodyRowCount > 0 && headerCount !== firstRowColCount) {
    console.error('My Queue table column mismatch:', headerCount, 'headers vs', firstRowColCount, 'cells')
    return
  }

  // General Options for DataTable
  const options = {
    pageLength: 50,
    order: [[2, 'desc']], // Sort by severity descending by default
    deferRender: true, // Improve performance for large datasets

    initComplete: function (settings, json) { // eslint-disable-line no-unused-vars
      $('div.loading').hide()
    },
    columnDefs: [
      // Expander column - not sortable, not searchable
      {
        targets: 0,
        orderable: false,
        searchable: false,
        className: 'dt-control'
      },
      // Severity column sorting
      {
        targets: 2,
        type: 'num'
      }
    ]
  }

  // Initialize Table
  let table
  try {
    table = $('#my-queue-data').DataTable(options)
  } catch (error) {
    console.error('My Queue DataTable initialization failed:', error)
    return
  }

  // Add event listener for opening and closing details
  $('#my-queue-data').on('click', 'td.dt-control', function () {
    const tr = $(this).closest('tr')
    const row = table.row(tr)

    if (row.child.isShown()) {
      // This row is already open - close it
      row.child.hide()
      tr.removeClass('shown')
    } else {
      // Open this row - fetch comments via AJAX
      const caseNumber = tr.data('case-number')

      // Show loading spinner
      row.child('<div class="text-center"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div></div>').show()
      tr.addClass('shown')

      // Fetch comments from API
      $.ajax({
        url: '/api/my-queue/case/' + caseNumber + '/comments',
        method: 'GET',
        success: function (data) {
          row.child(format(data)).show()
        },
        error: function () {
          row.child('<div class="alert alert-danger">Failed to load comments</div>').show()
        }
      })
    }
  })
})
