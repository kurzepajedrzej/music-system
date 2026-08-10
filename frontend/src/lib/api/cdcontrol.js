// cd-control-service client
// Commands go through backend: /api/cd/*

const BASE = '/api/cd';

export async function getStatus() {
	const r = await fetch(`${BASE}/status`);
	return r.json();
}

export async function sendCommand(cmd) {
	await fetch(`${BASE}/${cmd}`, { method: 'POST' });
}
