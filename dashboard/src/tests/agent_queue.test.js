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
  const element = {
    ready: function () {},
    addClass: function () { return this },
    removeClass: function () { return this }
  }
  function $ (selector) {
    return Object.assign({}, element, {
      text: function (value) { texts[selector] = value; return this }
    })
  }
  $.ajax = function (options) { requests.push(options) }
  const context = vm.createContext({
    $, document: {},
    sessionStorage: { setItem: function () {}, removeItem: function () {} },
    setTimeout: function (callback, delay) { timers.push({ callback, delay }) }
  })
  vm.runInContext(source, context)
  vm.runInContext("currentCaseNumber = '01234567'", context)
  return { context, requests, timers, texts }
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

test('missing position retains the generic pending message', function () {
  const { context, requests, texts } = setup()
  context.pollStatus('task-1', '01234567')
  requests[0].success({ state: 'PENDING' })
  requests[1].success({ state: 'not_found', position: null, queue_length: 0 })
  assert.equal(texts['#analysis-status-text'], 'Queued, waiting for worker...')
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
