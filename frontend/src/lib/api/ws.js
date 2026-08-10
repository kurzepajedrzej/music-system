// Unified WebSocket client
// Receives multiplexed state + tick messages from music-backend

export function connectWs(onState, onTick, onCd) {
	const wsBase = location.origin.replace(/^http/, 'ws');
	let current = null;
	let closedByCaller = false;

	function open() {
		if (current) current.close();
		current = new WebSocket(`${wsBase}/api/ws`);
		current.onmessage = (e) => {
			try {
				const msg = JSON.parse(e.data);
				if (msg.type === 'state') onState(msg);
				else if (msg.type === 'tick') onTick(msg);
				else if (msg.type === 'cd') onCd(msg);
			} catch {}
		};
		current.onclose = () => {
			if (!closedByCaller) setTimeout(open, 3000);
		};
	}
	open();

	return {
		close() {
			closedByCaller = true;
			current?.close();
		}
	};
}
