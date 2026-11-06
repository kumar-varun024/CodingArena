import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ArenaApi, canonical, readJournal } from './api';
import type { Health, Match } from './types';
import { startFixture } from './test/fixture';

let fixture: Awaited<ReturnType<typeof startFixture>>;
beforeAll(async () => { fixture = await startFixture(); });
afterAll(() => fixture.close());
beforeEach(() => { localStorage.clear(); vi.unstubAllGlobals(); });

describe('the actual HTTP API client', () => {
  it('uses fixture mode for JSON, API errors and text artifacts without changing body shapes', async () => {
    const api = new ArenaApi(fixture.baseUrl);
    expect((await api.get<Health>('/health')).mode).toBe('fixture');
    expect(api.mode).toBe('fixture');
    await expect(api.get('/matches/fixture-decision')).rejects.toMatchObject({ code: 'UNAUTHORIZED', status: 401 });
    api.setToken('fixture-operator');
    const match = await api.get<Match>('/matches/fixture-decision');
    expect(match.provider_labels).toEqual({ a: null, b: null });
    const log = await api.artifact(match.slots.a.candidate!.verification.log_artifact_id!);
    expect(log.text.toLowerCase()).toContain('fixture');
    expect(api.mode).toBe('fixture');
  });
  it('journals before dispatch and replays the identical ID/body after a lost response', async () => {
    const api = new ArenaApi(fixture.baseUrl);
    api.setToken('fixture-operator');
    await api.get('/health');
    const actualFetch = globalThis.fetch;
    const observed: string[] = [];
    let loseResponse = true;
    vi.stubGlobal('fetch', async (url: string, options: RequestInit) => {
      expect(readJournal()[0].state).toBe('pending');
      expect(JSON.stringify(readJournal())).not.toContain('fixture-operator');
      observed.push(String(options.body));
      const response = await actualFetch(url, options);
      if (loseResponse) { loseResponse = false; throw new TypeError('Connection lost after server committed.'); }
      return response;
    });
    const payload = { selection: 'neither', candidate_id: null, expected_evidence_key: null, reason: 'Recorded checks did not establish an acceptable candidate.' };
    await expect(api.mutate('/matches/fixture-neither/selection', payload)).rejects.toMatchObject({ code: 'AMBIGUOUS_REQUEST' });
    const saved = readJournal()[0];
    expect(saved.state).toBe('ambiguous');
    const result = await api.retry<Match>(saved);
    expect(result.phase).toBe('complete');
    expect(observed[0]).toBe(observed[1]);
    expect(readJournal()[0].state).toBe('completed');
    await expect(api.mutate(saved.path, { ...payload, reason: 'Changed body' }, saved.request_id)).rejects.toMatchObject({ code: 'IDEMPOTENCY_CONFLICT' });
  });
  it('refuses mutations when durable storage fails', async () => {
    const api = new ArenaApi(fixture.baseUrl); api.setToken('fixture-operator');
    await api.get('/health');
    const fetchSpy = vi.fn(); vi.stubGlobal('fetch', fetchSpy);
    const storageSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Full storage'); });
    await expect(api.mutate('/matches', {})).rejects.toMatchObject({ code: 'JOURNAL_ERROR' });
    expect(fetchSpy).not.toHaveBeenCalled(); storageSpy.mockRestore();
  });
  it('marks missing or contradictory mode headers as unknown', async () => {
    const api = new ArenaApi(fixture.baseUrl);
    for (const headers of ([{ 'content-type': 'application/json' }, { 'content-type': 'application/json', 'X-Arena-Mode': 'live' }] as Record<string, string>[])) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ mode: 'fixture' }), { headers })));
      await expect(api.get('/health')).rejects.toMatchObject({ code: 'PROTOCOL_ERROR' });
      expect(api.mode).toBeNull();
    }
  });
  it('preserves boolean and integer distinctions in canonical operations', () => {
    expect(canonical({ expected: true })).not.toBe(canonical({ expected: 1 }));
    expect(canonical({ b: 2, a: 1 })).toBe(canonical({ a: 1, b: 2 }));
  });
});
