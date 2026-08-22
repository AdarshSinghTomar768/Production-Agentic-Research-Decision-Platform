import { describe, expect, it } from 'vitest'
import { formatCost, formatMs, formatNumber, formatPercent } from './format'

describe('formatCost', () => {
  it('formats zero as $0.00', () => {
    expect(formatCost(0)).toBe('$0.00')
  })

  it('uses four decimals below one dollar', () => {
    expect(formatCost(0.01234)).toBe('$0.0123')
  })

  it('uses two decimals at or above one dollar', () => {
    expect(formatCost(12.345)).toBe('$12.35')
  })
})

describe('formatNumber', () => {
  it('adds thousands separators', () => {
    expect(formatNumber(1234567)).toBe('1,234,567')
  })
})

describe('formatPercent', () => {
  it('converts a ratio to a percentage string', () => {
    expect(formatPercent(0.856)).toBe('85.6%')
  })
})

describe('formatMs', () => {
  it('keeps milliseconds under one second', () => {
    expect(formatMs(842)).toBe('842ms')
  })

  it('switches to seconds above one second', () => {
    expect(formatMs(2345)).toBe('2.35s')
  })
})
