import { describe, expect, it } from 'vitest'

// Everything under ui/src except tests and test helpers.
const sources = import.meta.glob(['/src/**/*.{ts,tsx,css}', '!/src/**/*.test.{ts,tsx}', '!/src/test-setup.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const MIN_PX = 16

function toPx(value: string, unit: string | undefined): number {
  const n = Number.parseFloat(value)
  return unit === 'rem' || unit === 'em' ? n * 16 : n
}

/** Returns each text-size use below 16 px found in a source file. */
export function findSmallText(source: string): string[] {
  const found: string[] = []
  for (const m of source.matchAll(/\btext-(xs|sm)\b/g)) found.push(m[0])
  for (const m of source.matchAll(/\btext-\[(\d*\.?\d+)(px|rem|em)\]/g)) {
    if (toPx(m[1], m[2]) < MIN_PX) found.push(m[0])
  }
  for (const m of source.matchAll(/font-?[sS]ize\s*:\s*['"]?(\d*\.?\d+)(px|rem|em)?['"]?/g)) {
    if (toPx(m[1], m[2] ?? 'px') < MIN_PX) found.push(m[0])
  }
  return found
}

describe('text is at least 16 px', () => {
  // React Flow's own stylesheet (its attribution link is 10 px) lives in
  // node_modules and is not scanned: a deliberate exception, see the spec.
  it('flags each way of writing small text', () => {
    expect(findSmallText('className="text-xs"')).toEqual(['text-xs'])
    expect(findSmallText('className="text-sm"')).toEqual(['text-sm'])
    expect(findSmallText('className="text-[12px]"')).toEqual(['text-[12px]'])
    expect(findSmallText('className="text-[0.75rem]"')).toEqual(['text-[0.75rem]'])
    expect(findSmallText('style={{ fontSize: 12 }}')).toHaveLength(1)
    expect(findSmallText("style={{ fontSize: '0.8em' }}")).toHaveLength(1)
    expect(findSmallText('a { font-size: 14px; }')).toHaveLength(1)
  })

  it('accepts 16 px and larger', () => {
    expect(findSmallText('className="text-base text-lg text-[16px] text-[1rem]"')).toEqual([])
    expect(findSmallText('a { font-size: 1rem; }')).toEqual([])
    expect(findSmallText('style={{ fontSize: 18 }}')).toEqual([])
  })

  it('finds the sources it is meant to scan', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(8)
    expect(Object.keys(sources).some((p) => p.endsWith('nodes.tsx'))).toBe(true)
    expect(Object.keys(sources).some((p) => p.endsWith('index.css'))).toBe(true)
  })

  it('finds no small text in the app', () => {
    const offenders = Object.entries(sources).flatMap(([path, text]) => findSmallText(text).map((hit) => `${path}: ${hit}`))
    expect(offenders).toEqual([])
  })
})
