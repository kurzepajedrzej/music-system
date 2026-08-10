// Music backend API client
// nginx proxies /api/* → music-backend:3000/api/*

const BASE = '/api';

export async function getOutputs() {
	const r = await fetch(`${BASE}/outputs`);
	const data = await r.json();
	return data.outputs ?? [];
}

export async function setOutput(id, { enabled, volume }) {
	const body = {};
	if (enabled !== undefined) body.selected = enabled;
	if (volume  !== undefined) body.volume   = volume;
	await fetch(`${BASE}/outputs/${id}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
}

// Library
export async function getAlbums() {
	const r = await fetch(`${BASE}/library/albums`);
	const d = await r.json();
	return d.items ?? [];
}

export async function getAlbumTracks(albumId) {
	const r = await fetch(`${BASE}/library/albums/${albumId}/tracks`);
	const d = await r.json();
	return d.items ?? [];
}

// Player — backend waits for OwnTone confirmation before responding
export async function getPlayer() {
	const r = await fetch(`${BASE}/player`);
	return r.json();
}

export async function playerCommand(cmd) {
	const r = await fetch(`${BASE}/player/${cmd}`, { method: 'PUT' });
	return r.json();
}

export async function seekTo(position_ms) {
	const r = await fetch(`${BASE}/player/seek?position_ms=${position_ms}`, { method: 'PUT' });
	return r.json();
}

// Queue — atomic operations handled by backend
export async function clearAndPlay(uri) {
	await fetch(`${BASE}/queue/play`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ uri })
	});
}

export async function addToQueue(uri) {
	await fetch(`${BASE}/queue/add`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ uri })
	});
}

export async function removeQueueItem(id) {
	await fetch(`${BASE}/queue/items/${id}`, { method: 'DELETE' });
}

export async function playQueueItem(id) {
	await fetch(`${BASE}/queue/items/${id}/play`, { method: 'PUT' });
}

export async function getQueue() {
	const r = await fetch(`${BASE}/queue`);
	return r.json();
}

// Search
export async function search(query) {
	const r = await fetch(`${BASE}/search?type=tracks,albums&query=${encodeURIComponent(query)}`);
	return r.json();
}

export async function setPlayerVolume(volume) {
	await fetch(`${BASE}/player/volume`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ volume })
	});
}

export function artworkUrl(albumId, size = 240) {
	return `${BASE}/artwork/album/${albumId}?maxwidth=${size}&maxheight=${size}`;
}

// Composite state — replaces localStorage cache
export async function getState() {
	const r = await fetch(`${BASE}/state`);
	return r.json();
}

// Source switching — stops playback and switches OwnTone input
export async function switchSource(source) {
	const r = await fetch(`${BASE}/source/${source}`, { method: 'POST' });
	return r.json();
}
