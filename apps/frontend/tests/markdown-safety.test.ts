import assert from 'node:assert/strict'
import test from 'node:test'

import { tokenizeMarkdownLine } from '../src/utils/markdown.ts'

test('keeps user supplied HTML in an escaped text token', () => {
  const payload = '<img src=x onerror="globalThis.pwned=true">'

  assert.deepEqual(tokenizeMarkdownLine(payload), [
    {
      type: 'text',
      content: payload,
    },
  ])
})

test('preserves the supported bold and inline-code formatting', () => {
  assert.deepEqual(tokenizeMarkdownLine('Use **safe text** and `code`.'), [
    { type: 'text', content: 'Use ' },
    { type: 'strong', content: 'safe text' },
    { type: 'text', content: ' and ' },
    { type: 'code', content: 'code' },
    { type: 'text', content: '.' },
  ])
})
