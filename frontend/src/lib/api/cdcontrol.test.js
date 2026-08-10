import { describe, it, expect, vi, beforeEach } from 'vitest';
import { sendCommand } from './cdcontrol.js';

describe('cdcontrol api client', () => {
	beforeEach(() => {
		vi.stubGlobal('fetch', vi.fn());
	});

	it('rejects when the response is not ok', async () => {
		fetch.mockResolvedValue({ ok: false, status: 503 });
		await expect(sendCommand('play')).rejects.toThrow(/503/);
	});

	it('resolves on a 2xx response', async () => {
		// The real backend (app/routers/cd.py) returns manager.status() as a JSON
		// body on every POST /api/cd/{cmd}, so the mock must provide json() too —
		// a bare { ok: true, status: 200 } makes request() throw on r.json().
		fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
		await expect(sendCommand('play')).resolves.toBeUndefined();
	});
});
