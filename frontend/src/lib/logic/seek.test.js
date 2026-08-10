import { describe, it, expect } from 'vitest';
import { computeSeekTarget } from './seek.js';

describe('computeSeekTarget', () => {
	it('computes position from percent and item length', () => {
		const { positionMs } = computeSeekTarget({
			player: { item_length_ms: 200000, state: 'play' },
			valuePercent: 50
		});
		expect(positionMs).toBe(100000);
	});

	it('preserves paused state instead of forcing playback to resume', () => {
		const { resumeState } = computeSeekTarget({
			player: { item_length_ms: 200000, state: 'pause' },
			valuePercent: 10
		});
		expect(resumeState).toBe('pause');
	});

	it('keeps playing state when seeking while already playing', () => {
		const { resumeState } = computeSeekTarget({
			player: { item_length_ms: 200000, state: 'play' },
			valuePercent: 10
		});
		expect(resumeState).toBe('play');
	});
});
