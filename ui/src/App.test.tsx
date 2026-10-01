import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  it('shows AgentFly v2', () => {
    render(<App />)
    expect(screen.getByText('AgentFly v2')).toBeTruthy()
  })
})
