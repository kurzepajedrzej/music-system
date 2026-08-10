export function computeSeekTarget({ player, valuePercent }) {
	const lengthMs = player?.item_length_ms ?? 0;
	const positionMs = Math.round((valuePercent / 100) * lengthMs);
	// Preserve whatever the player was doing before the seek — a seek must
	// never force a paused track to resume playing.
	const resumeState = player?.state === 'pause' ? 'pause' : 'play';
	return { positionMs, resumeState };
}
