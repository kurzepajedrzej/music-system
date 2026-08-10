import { describe, it, expect, vi } from 'vitest';
import { switchSource } from './source.js';

describe('switchSource', () => {
	it('toggles cd -> library and calls the API with the target', async () => {
		const apiSwitchSource = vi.fn().mockResolvedValue({});
		const result = await switchSource({ current: 'cd', target: 'library', apiSwitchSource });
		expect(apiSwitchSource).toHaveBeenCalledWith('library');
		expect(result).toBe('library');
	});

	it('propagates a rejection without changing the reported source', async () => {
		const apiSwitchSource = vi.fn().mockRejectedValue(new Error('502'));
		await expect(
			switchSource({ current: 'cd', target: 'library', apiSwitchSource })
		).rejects.toThrow('502');
	});

	it('rejects immediately if a switch is already in flight, without calling the API again', async () => {
		let resolveFirst;
		const apiSwitchSource = vi.fn().mockReturnValue(new Promise((res) => (resolveFirst = res)));
		const first = switchSource({ current: 'cd', target: 'library', apiSwitchSource });
		await expect(
			switchSource({ current: 'cd', target: 'library', apiSwitchSource })
		).rejects.toThrow('switch already in progress');
		resolveFirst({});
		await first;
		expect(apiSwitchSource).toHaveBeenCalledTimes(1);
	});
});
