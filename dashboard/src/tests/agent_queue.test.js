const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

const source = fs.readFileSync(path.join(__dirname, '../t5gweb/static/js/agent.js'), 'utf8')

function setup () {
  const requests = []
  const timers = []
  const texts = {}
  const storage = {}
  const element = {
    ready: function () {},
    addClass: function () { return this },
    removeClass: function () { return this },
    val: function () { return this }
  }
  function $ (selector) {
    return Object.assign({}, element, {
      text: function (value) { texts[selector] = value; return this }
    })
  }
  $.ajax = function (options) { requests.push(options) }
  const context = vm.createContext({
    $,
    document: {},
    sessionStorage: {
      setItem: function (key, value) { storage[key] = String(value) },
      getItem: function (key) {
        return Object.prototype.hasOwnProperty.call(storage, key) ? storage[key] : null
      },
      removeItem: function (key) { delete storage[key] }
    },
    setTimeout: function (callback, delay) { timers.push({ callback, delay }) }
  })
  vm.runInContext(source, context)
  vm.runInContext("currentCaseNumber = '01234567'", context)
  return { context, requests, timers, texts, storage }
}

// Submits the current case and accepts it as taskId, without queue metadata.
function submitAccepted (context, requests, taskId) {
  context.triggerAnalysis(false)
  requests[requests.length - 1].success({ task_id: taskId, queue_position: null, queue_length: null })
}

function posts (requests) {
  return requests.filter(function (r) { return r.method === 'POST' })
}

test('ordinal handles endings and the teen exceptions', function () {
  const { context } = setup()
  const expected = ['1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '23rd', '101st', '111th', '112th', '113th']
  for (const value of expected) {
    assert.equal(context.ordinal(parseInt(value, 10)), value)
  }
})

test('submission displays the supplied queue position', function () {
  const { context, requests, texts } = setup()
  context.triggerAnalysis(false)
  requests[0].success({ task_id: 'task-1', queue_position: 2, queue_length: 4 })
  assert.equal(texts['#analysis-status-text'], 'You are 2nd of 4 in the analysis queue')
})

test('submission without queue metadata retains the original message', function () {
  const { context, requests, texts } = setup()
  context.triggerAnalysis(false)
  requests[0].success({ task_id: 'task-1', queue_position: null, queue_length: null })
  assert.equal(texts['#analysis-status-text'], 'Task queued. Polling for completion...')
})

test('pending polls show live positions and keep the three-second cadence', function () {
  const { context, requests, timers, texts } = setup()
  context.pollStatus('task-1', '01234567')
  requests[0].success({ state: 'PENDING' })
  // No generic placeholder before the position reply: writing both flickers.
  assert.equal(texts['#analysis-status-text'], undefined)
  assert.equal(requests[1].url, '/api/ai/queue/position/01234567')
  assert.equal(requests[1].method, 'GET')
  requests[1].success({ state: 'queued', position: 21, queue_length: 23 })
  assert.equal(texts['#analysis-status-text'], 'You are 21st of 23 in the analysis queue')
  assert.equal(timers[0].delay, 3000)
})

test('a task already held by the worker shows it is next in line', function () {
  const { context, requests, texts } = setup()
  context.pollStatus('task-1', '01234567')
  requests[0].success({ state: 'PENDING' })
  requests[1].success({ state: 'not_found', position: null, queue_length: 1 })
  assert.equal(texts['#analysis-status-text'], 'Next in line: waiting for the current analysis to finish')
})

test('queue request failures fall back to the generic pending message', function () {
  const { context, requests, timers, texts } = setup()
  context.pollStatus('task-1', '01234567')
  requests[0].success({ state: 'PENDING' })
  requests[1].error()
  assert.equal(texts['#analysis-status-text'], 'Queued, waiting for worker...')
  assert.equal(vm.runInContext('pollErrorCount', context), 0)
  assert.equal(timers[0].delay, 3000)
})

test('a delayed queue response cannot overwrite STARTED', function () {
  const { context, requests, timers, texts } = setup()
  context.pollStatus('task-1', '01234567')
  requests[0].success({ state: 'PENDING' })
  const positionRequest = requests[1]
  timers[0].callback()
  requests[2].success({ state: 'STARTED' })
  positionRequest.success({ state: 'queued', position: 1, queue_length: 3 })
  assert.equal(texts['#analysis-status-text'], 'Running AI analysis...')
  assert.equal(requests.length, 3)
})

test('a delayed queue response cannot overwrite a status retry message', function () {
  const { context, requests, timers, texts } = setup()
  context.pollStatus('task-1', '01234567')
  requests[0].success({ state: 'PENDING' })
  timers[0].callback()
  requests[2].error()
  requests[1].success({ state: 'queued', position: 1, queue_length: 3 })
  assert.equal(texts['#analysis-status-text'], 'Connection issue, retrying... (1/5)')
  assert.equal(timers[1].delay, 5000)
})

test('a poll retried after a connection error keeps the case number', function () {
  const { context, requests, timers, texts } = setup()
  context.pollStatus('task-1', '01234567')
  requests[0].error()
  assert.equal(timers[0].delay, 5000)
  timers[0].callback()
  assert.equal(requests[1].url, '/api/ai/status/task-1')
  requests[1].success({ state: 'PENDING' })
  assert.equal(requests[2].url, '/api/ai/queue/position/01234567')
  requests[2].success({ state: 'queued', position: 2, queue_length: 3 })
  assert.equal(texts['#analysis-status-text'], 'You are 2nd of 3 in the analysis queue')
  assert.equal(timers[1].delay, 3000)
})

test('no position request once the analysis has started', function () {
  const { context, requests, texts } = setup()
  context.pollStatus('task-1', '01234567')
  requests[0].success({ state: 'STARTED' })
  assert.equal(requests.length, 1)
  assert.equal(texts['#analysis-status-text'], 'Running AI analysis...')
})

test('positions are dropped after the user moved on to another case', function () {
  const { context, requests, texts } = setup()
  context.pollStatus('task-1', '01234567')
  requests[0].success({ state: 'PENDING' })
  vm.runInContext("currentCaseNumber = '08765432'", context)
  requests[1].success({ state: 'queued', position: 3, queue_length: 5 })
  assert.equal(texts['#analysis-status-text'], undefined)
})

test('a stale status reply cannot overwrite the newer loop', function () {
  const { context, requests, texts } = setup()
  context.pollStatus('task-1', '01234567')
  context.pollStatus('task-2', '01234567')
  requests[0].success({ state: 'STARTED' })
  assert.equal(texts['#analysis-status-text'], undefined)
  requests[1].success({ state: 'STARTED' })
  assert.equal(texts['#analysis-status-text'], 'Running AI analysis...')
})

test('a superseded loop stops requesting after its timer fires', function () {
  const { context, requests, timers, texts } = setup()
  context.pollStatus('task-1', '01234567')
  requests[0].success({ state: 'PENDING' })
  context.pollStatus('task-2', '01234567')
  requests[2].success({ state: 'STARTED' })
  timers[0].callback()
  requests[1].success({ state: 'queued', position: 1, queue_length: 3 })
  assert.equal(requests.length, 3)
  assert.equal(texts['#analysis-status-text'], 'Running AI analysis...')
})

test('resubmitting the analyzing case resumes its task instead of stacking a new one', function () {
  const { context, requests, texts } = setup()
  submitAccepted(context, requests, 'task-1')
  context.triggerAnalysis(false)
  assert.equal(posts(requests).length, 1)
  assert.equal(texts['#analysis-status-text'], 'Analysis already in progress...')
  assert.equal(requests[requests.length - 1].url, '/api/ai/status/task-1')
})

test('an expired stored analysis no longer blocks a fresh submission', function () {
  const { context, requests, storage } = setup()
  submitAccepted(context, requests, 'task-1')
  storage.activeAnalysis = JSON.stringify({ task_id: 'task-1', case_number: '01234567', started_at: Date.now() - 3 * 60 * 60 * 1000 })
  context.triggerAnalysis(false)
  assert.equal(posts(requests).length, 2)
  assert.equal(posts(requests)[1].url, '/api/ai/analyze/01234567')
})

test('submitting a different case still creates a new analysis', function () {
  const { context, requests } = setup()
  submitAccepted(context, requests, 'task-1')
  vm.runInContext("currentCaseNumber = '08765432'", context)
  context.triggerAnalysis(false)
  assert.equal(posts(requests).length, 2)
  assert.equal(posts(requests)[1].url, '/api/ai/analyze/08765432')
})

test('re-analyze bypasses the stored analysis and submits with force', function () {
  const { context, requests } = setup()
  submitAccepted(context, requests, 'task-1')
  context.triggerAnalysis(true)
  assert.equal(posts(requests).length, 2)
  assert.equal(posts(requests)[1].url, '/api/ai/analyze/01234567?force=true')
})

test('a page reload resumes polling the stored analysis', function () {
  const { context, requests, texts, storage } = setup()
  storage.activeAnalysis = JSON.stringify({ task_id: 'task-1', case_number: '08765432', started_at: Date.now() })
  context.resumeOngoingAnalysis()
  assert.equal(vm.runInContext('currentCaseNumber', context), '08765432')
  assert.equal(texts['#analysis-status-text'], 'Resuming analysis...')
  assert.equal(requests.length, 1)
  assert.equal(requests[0].url, '/api/ai/status/task-1')
})

test('a page reload clears an expired or unreadable stored analysis', function () {
  for (const value of [JSON.stringify({ task_id: 'task-1', case_number: '01234567', started_at: Date.now() - 3 * 60 * 60 * 1000 }), '{not json']) {
    const { context, requests, storage } = setup()
    storage.activeAnalysis = value
    context.resumeOngoingAnalysis()
    assert.equal(requests.length, 0)
    assert.equal(storage.activeAnalysis, undefined)
  }
})
