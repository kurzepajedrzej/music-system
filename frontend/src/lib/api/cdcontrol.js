// cd-control client
// Commands go through the backend: /api/cd/*

const BASE = '/api/cd';
const TIMEOUT_MS = 8000;

async function request(path, options = {}) {
	const r = await fetch(`${BASE}${path}`, { ...options, signal: AbortSignal.timeout(TIMEOUT_MS) });
	if (!r.ok) {
		throw new Error(`${options.method ?? 'GET'} ${path} -> ${r.status}`);
	}
	return r.status === 204 ? null : r.json();
}

export async function getStatus() {
	return request('/status');
}

export async function sendCommand(cmd) {
	await request(`/${cmd}`, { method: 'POST' });
}
