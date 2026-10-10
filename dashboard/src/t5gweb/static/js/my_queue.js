// My Queue DataTable initialization
/* globals $ */ // eslint-disable-line no-redeclare

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
      result += '<div class=\'fw-bold\'>' + (comment.author || 'Unknown') +
        (typeLabel ? ' <span class=\'fw-normal text-muted\'>(' + typeLabel + ')</span>' : '') + '</div>'
      result += '<div class=\'text-muted small\'>' +
        (comment.date ? comment.date.substring(0, 19).replace('T', ' ') : 'No date') + '</div>'
      result += '<div class=\'mt-2\'>' + (comment.body || '') + '</div>'
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
      result += '<div class=\'fw-bold\'>' + (comment.author || 'Unknown') + '</div>'
      result += '<div class=\'text-muted small\'>' +
        (comment.updated ? comment.updated.substring(0, 19).replace('T', ' ') : 'No date') + '</div>'
      result += '<div class=\'mt-2\'>' + (comment.body || '') + '</div>'
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
  console.log('My Queue: DOM ready')

  // Check if table exists
  const tableElement = $('#my-queue-data')
  if (tableElement.length === 0) {
    console.error('My Queue table #my-queue-data not found!')
    return
  }

  console.log('Table found, rows:', tableElement.find('tbody tr').length)

  // Debug: Check column counts
  const headerCount = tableElement.find('thead tr th').length
  const firstRowColCount = tableElement.find('tbody tr:first td').length
  console.log('Header columns:', headerCount)
  console.log('First row columns:', firstRowColCount)

  if (headerCount !== firstRowColCount) {
    console.error('COLUMN MISMATCH! Headers:', headerCount, 'Cells:', firstRowColCount)
    alert('Table structure error: ' + headerCount + ' headers but ' + firstRowColCount + ' cells in first row')
    return
  }

  // General Options for DataTable
  const options = {
    pageLength: 50,
    order: [[2, 'desc']], // Sort by severity descending by default
    deferRender: true, // Improve performance for large datasets

    initComplete: function (settings, json) { // eslint-disable-line no-unused-vars
      console.log('DataTable initComplete called')
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

  // Initialize Table with options and error handling
  let table
  try {
    console.log('Initializing DataTable...')
    table = $('#my-queue-data').DataTable(options)
    console.log('DataTable initialized successfully')
  } catch (error) {
    console.error('DataTable initialization error:', error)
    alert('Error initializing table: ' + error.message + '. Check console for details.')
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
