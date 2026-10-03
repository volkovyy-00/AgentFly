/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { EDGE_COLOR } from './layout'
import { DECOR, TONES } from './tones'

/** Pairs set in index.css, not by a class: React Flow's attribution link. */
const CSS_ONLY_PAIRS = [{ name: 'attribution', bg: 'canvas', text: 'muted' }] as const

const here = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(join(here, '../index.css'), 'utf8')

function token(name: string): string {
  const match = new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})`).exec(css)
  if (match === null) throw new Error(`no token --color-${name} in index.css`)
  return match[1].toLowerCase()
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16) / 255).map((v) =>
    v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4,
  )
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

describe('contrast helper', () => {
  it('matches known values', () => {
    expect(contrast('#ffffff', '#000000')).toBeCloseTo(21)
    expect(contrast('#e6edf3', '#0e1116')).toBeCloseTo(16, 0)
  })
})

describe('text pairs', () => {
  it.each(Object.entries(TONES))('%s: text is at least 7:1 on its background', (_name, tone) => {
    expect(contrast(token(tone.text), token(tone.bg))).toBeGreaterThanOrEqual(7)
  })

  it.each(CSS_ONLY_PAIRS)('css-only pair %j is at least 7:1', ({ bg, text }) => {
    expect(contrast(token(text), token(bg))).toBeGreaterThanOrEqual(7)
  })

  it('keeps muted text off the tinted fills', () => {
    for (const [name, tone] of Object.entries(TONES)) {
      if (tone.text === 'muted') expect(['canvas', 'surface'], name).toContain(tone.bg)
    }
  })

  it('has classes that name exactly the tokens in the table', () => {
    for (const [name, tone] of Object.entries(TONES)) {
      const expected = [`bg-${tone.bg}`, `text-${tone.text}`, ...(tone.border === null ? [] : [`border-${tone.border}`])]
      expect(tone.classes.split(/\s+/).sort(), name).toEqual(expected.sort())
    }
  })
})

describe('non-text contrast', () => {
  it.each(Object.entries(TONES).filter(([, t]) => t.border !== null))('%s border is at least 3:1 on canvas', (_n, tone) => {
    expect(contrast(token(tone.border!), token('canvas'))).toBeGreaterThanOrEqual(3)
  })

  it.each(Object.entries(DECOR).filter(([, d]) => d.token !== null))('decoration %s is at least 3:1 on canvas', (_n, d) => {
    expect(contrast(token(d.token!), token('canvas'))).toBeGreaterThanOrEqual(3)
  })

  it.each(Object.entries(EDGE_COLOR))('edge colour %s is at least 3:1 on canvas', (_n, hex) => {
    expect(contrast(hex, token('canvas'))).toBeGreaterThanOrEqual(3)
  })
})

describe('colour lives in one place', () => {
  const sources = import.meta.glob(['/src/**/*.{ts,tsx}', '!/src/**/*.test.{ts,tsx}', '!/src/test-setup.ts', '!/src/graph/tones.ts'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>

  const COLOUR = /\b(?:bg|text|border|ring|fill|stroke|outline)-(?:canvas|surface|ink|muted|fill-[a-z]+|chip-[a-z]+|chain|aux|secret|blocked|warned|link|white|black|step|rule|rule-edge)\b/g

  it('finds the sources it is meant to scan', () => {
    expect(Object.keys(sources).some((p) => p.endsWith('nodes.tsx'))).toBe(true)
    expect(Object.keys(sources).some((p) => p.endsWith('App.tsx'))).toBe(true)
  })

  it('finds no colour utility class outside tones.ts', () => {
    const offenders = Object.entries(sources).flatMap(([path, text]) => [...text.matchAll(COLOUR)].map((m) => `${path}: ${m[0]}`))
    expect(offenders).toEqual([])
  })

  it('recolours the React Flow attribution link with a passing pair', () => {
    expect(css).toMatch(/\.react-flow__attribution[^}]*a[^}]*var\(--color-muted\)/s)
  })
})
