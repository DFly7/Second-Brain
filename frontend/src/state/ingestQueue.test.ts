import { describe, expect, it } from 'vitest'
import { reduceQueue, type QueueState } from './ingestQueue'

function mkState(status: 'done' | 'queued', createdAt: string): QueueState {
  return {
    items: [
      {
        id: 'a',
        fileName: 'a.pdf',
        fileSize: 123,
        createdAt,
        status,
        sourceId: 'src-a',
      },
    ],
  }
}

describe('reduceQueue', () => {
  it('patches by sourceId', () => {
    const s0 = mkState('queued', new Date().toISOString())
    const s1 = reduceQueue(s0, { type: 'patch_by_source', sourceId: 'src-a', patch: { status: 'done' } })
    expect(s1.items[0].status).toBe('done')
  })

  it('keeps non-terminal items even if old', () => {
    const old = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString()
    const s0 = mkState('queued', old)
    const s1 = reduceQueue(s0, { type: 'prune', nowMs: Date.now() })
    expect(s1.items).toHaveLength(1)
    expect(s1.items[0].status).toBe('queued')
  })
})
