import { describe, expect, it } from 'vitest'
import { viewHref, viewOf } from './ViewTabs'

describe('viewOf', () => {
  it('is the trail unless the address says view=graph', () => {
    expect(viewOf('')).toBe('trail')
    expect(viewOf('?view=trail')).toBe('trail')
    expect(viewOf('?view=graph')).toBe('graph')
    expect(viewOf('?mock=1&view=graph&len=5')).toBe('graph')
    expect(viewOf('?view=Graph')).toBe('trail')
    expect(viewOf('?view=')).toBe('trail')
  })
})

describe('viewHref', () => {
  it('makes the trail plain / and the graph ?view=graph', () => {
    expect(viewHref('trail', '')).toBe('/')
    expect(viewHref('graph', '')).toBe('/?view=graph')
  })
  it('drops view=trail and view=graph when going to the trail, and keeps the rest', () => {
    expect(viewHref('trail', '?view=graph')).toBe('/')
    expect(viewHref('trail', '?view=trail&mock=1')).toBe('/?mock=1')
    expect(viewHref('trail', '?mock=1&view=graph&len=60')).toBe('/?mock=1&len=60')
  })
  it('sets view=graph once, keeping the rest', () => {
    expect(viewHref('graph', '?mock=1&len=60')).toBe('/?mock=1&len=60&view=graph')
    expect(viewHref('graph', '?view=graph&mock=1')).toBe('/?view=graph&mock=1')
  })
})
