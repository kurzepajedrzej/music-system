export type PlayerCommand = 'play' | 'pause' | 'stop' | 'next' | 'previous';

export async function playerCommand(cmd: PlayerCommand): Promise<void> {
  const res = await fetch(`/api/player/${cmd}`, { method: 'PUT' });
  if (!res.ok) {
    throw new Error(`player ${cmd} failed: ${res.status}`);
  }
}

export async function setMasterVolume(volume: number): Promise<void> {
  const res = await fetch('/api/player/volume', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ volume })
  });
  if (!res.ok) {
    throw new Error(`set volume failed: ${res.status}`);
  }
}

export type CdCommand =
  | 'play'
  | 'pause'
  | 'stop'
  | 'next'
  | 'prev'
  | 'open-close'
  | 'disc-next'
  | 'disc-prev'
  | 'repeat'
  | 'random';

export async function cdCommand(cmd: CdCommand): Promise<void> {
  const res = await fetch(`/api/cd/${cmd}`, { method: 'POST' });
  if (!res.ok) {
    throw new Error(`cd ${cmd} failed: ${res.status}`);
  }
}

export type SourceTarget = 'cd' | 'library';

export async function switchSource(target: SourceTarget): Promise<void> {
  const res = await fetch(`/api/source/${target}`, { method: 'POST' });
  if (!res.ok) {
    throw new Error(`switch to ${target} failed: ${res.status}`);
  }
}

export interface Album {
  id: string;
  name: string;
  artist: string;
  track_count: number;
  data_kind?: string;
  uri: string;
}

export async function getAlbums(): Promise<Album[]> {
  const res = await fetch('/api/library/albums');
  if (!res.ok) {
    throw new Error(`get albums failed: ${res.status}`);
  }
  const data = await res.json();
  const items: Album[] = data.items ?? [];
  // The pipe passthrough (CD/line-in audio) shows up as a 1-track "Unknown
  // album" — it's not a real library track, so it never belongs in a track
  // list a user is browsing.
  return items.filter((album) => album.data_kind !== 'pipe');
}

export interface Track {
  id: number;
  title: string;
  track_number: number;
  length_ms: number;
  uri: string;
}

export async function getAlbumTracks(albumId: string): Promise<Track[]> {
  const res = await fetch(`/api/library/albums/${albumId}/tracks`);
  if (!res.ok) {
    throw new Error(`get album tracks failed: ${res.status}`);
  }
  const data = await res.json();
  return data.items ?? [];
}

export async function playTrack(uri: string): Promise<void> {
  const res = await fetch('/api/queue/play', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ uri })
  });
  if (!res.ok) {
    throw new Error(`play track failed: ${res.status}`);
  }
}

export interface Output {
  id: string;
  name: string;
  type: string;
  selected: boolean;
  volume: number;
}

export async function getOutputs(): Promise<Output[]> {
  const res = await fetch('/api/outputs');
  if (!res.ok) {
    throw new Error(`get outputs failed: ${res.status}`);
  }
  const data = await res.json();
  const outputs: Output[] = data.outputs ?? [];
  // Only AirPlay speakers are meant to be controlled here -- Chromecast and
  // the server's own ALSA output aren't part of this control surface.
  return outputs.filter((output) => output.type.startsWith('AirPlay'));
}

export async function setOutput(id: string, body: { selected?: boolean; volume?: number }): Promise<void> {
  const res = await fetch(`/api/outputs/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) {
    throw new Error(`set output ${id} failed: ${res.status}`);
  }
}
