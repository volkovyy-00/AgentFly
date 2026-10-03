/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const pkg = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../package.json'), 'utf8')) as {
  dependencies: Record<string, string>
}

describe('pinned dependencies', () => {
  it.each(['@xyflow/react', 'motion'])('%s is pinned exactly (no ^ or ~)', (name) => {
    expect(pkg.dependencies[name]).toMatch(/^\d+\.\d+\.\d+$/)
  })
})
