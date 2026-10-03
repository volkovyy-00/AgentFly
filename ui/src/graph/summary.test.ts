import { describe, expect, it } from 'vitest'
import { summaryText } from './summary'
import { makeHidden } from './testing'

describe('summaryText', () => {
  it('puts the alarms in brackets and drops zero counts', () => {
    expect(summaryText(makeHidden({ total: 38, read: 20, shell: 16, tool: 2, blocked: 2, warned: 1 }))).toBe(
      '38 earlier steps (2 blocked, 1 warned): 20 read, 16 shell, 2 tool',
    )
  })

  it('has no brackets without alarms', () => {
    expect(summaryText(makeHidden({ total: 12, shell: 12 }))).toBe('12 earlier steps: 12 shell')
  })

  it('says step for one, and survives kinds the page does not count', () => {
    expect(summaryText(makeHidden({ total: 1 }))).toBe('1 earlier step')
    expect(summaryText(makeHidden({ total: 3, edit: 1, warned: 1 }))).toBe('3 earlier steps (1 warned): 1 edit')
  })
})
