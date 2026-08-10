import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getOutputs, playerCommand } from './owntone.js';

describe('owntone api client', () => {
	beforeEach(() => {
		vi.stubGlobal('fetch', vi.fn());
	});

	it('rejects when the response is not ok', async () => {
		fetch.mockResolvedValue({ ok: false, status: 500, json: async () => ({}) });
		await expect(playerCommand('play')).rejects.toThrow(/500/);
	});

	it('resolves normally on a 2xx response', async () => {
		fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ outputs: [{ id: 1 }] }) });
		const outputs = await getOutputs();
		expect(outputs).toEqual([{ id: 1 }]);
	});

	it('passes an AbortSignal so requests do not hang forever', async () => {
		fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ outputs: [] }) });
		await getOutputs();
		const [, options] = fetch.mock.calls[0];
		expect(options.signal).toBeInstanceOf(AbortSignal);
	});
});
