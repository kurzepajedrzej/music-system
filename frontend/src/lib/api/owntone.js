// Music backend API client
// nginx proxies /api/* → music-backend:3000/api/*

const BASE = '/api';
const TIMEOUT_MS = 8000;

async function request(path, options = {}) {
	const r = await fetch(`${BASE}${path}`, { ...options, signal: AbortSignal.timeout(TIMEOUT_MS) });
	if (!r.ok) {
		throw new Error(`${options.method ?? 'GET'} ${path} -> ${r.status}`);
	}
	if (r.status === 204) return null;
	return r.json();
}

export async function getOutputs() {
	const data = await request('/outputs');
	return data.outputs ?? [];
}

export async function setOutput(id, { enabled, volume }) {
	const body = {};
	if (enabled !== undefined) body.selected = enabled;
	if (volume !== undefined) body.volume = volume;
	await request(`/outputs/${id}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
}

export async function getAlbums() {
	const d = await request('/library/albums');
	return d.items ?? [];
}

export async function getAlbumTracks(albumId) {
	const d = await request(`/library/albums/${albumId}/tracks`);
	return d.items ?? [];
}

export async function getPlayer() {
	return request('/player');
}

export async function playerCommand(cmd) {
	return request(`/player/${cmd}`, { method: 'PUT' });
}

export async function seekTo(position_ms) {
	return request(`/player/seek?position_ms=${position_ms}`, { method: 'PUT' });
}

export async function clearAndPlay(uri) {
	await request('/queue/play', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ uri })
	});
}

export async function addToQueue(uri) {
	await request('/queue/add', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ uri })
	});
}

export async function removeQueueItem(id) {
	await request(`/queue/items/${id}`, { method: 'DELETE' });
}

export async function playQueueItem(id) {
	await request(`/queue/items/${id}/play`, { method: 'PUT' });
}

export async function getQueue() {
	return request('/queue');
}

export async function search(query) {
	return request(`/search?type=tracks,albums&query=${encodeURIComponent(query)}`);
}

export async function setPlayerVolume(volume) {
	await request('/player/volume', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ volume })
	});
}

export function artworkUrl(albumId, size = 240) {
	return `${BASE}/artwork/album/${albumId}?maxwidth=${size}&maxheight=${size}`;
}

export async function getState() {
	return request('/state');
}

export async function switchSource(source) {
	return request(`/source/${source}`, { method: 'POST' });
}
