// Unified WebSocket client
// Receives multiplexed state + tick messages from music-backend

export function connectWs(onState, onTick, onCd) {
	const wsBase = location.origin.replace(/^http/, 'ws');
	const ws = new WebSocket(`${wsBase}/api/ws`);
	ws.onmessage = (e) => {
		try {
			const msg = JSON.parse(e.data);
			if (msg.type === 'state') onState(msg);
			else if (msg.type === 'tick') onTick(msg);
			else if (msg.type === 'cd') onCd(msg);
		} catch {}
	};
	ws.onclose = () => setTimeout(() => connectWs(onState, onTick, onCd), 3000);
	return ws;
}
