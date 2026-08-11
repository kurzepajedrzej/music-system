import { useEffect, useState } from 'react';
import { useLiveState } from '../lib/liveState';
import { getAlbumTracks, getAlbums, playTrack, type Album, type Track } from '../lib/api';

function formatDuration(ms: number): string {
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

export default function Library() {
  const { currentTrack } = useLiveState();
  const [albums, setAlbums] = useState<Album[]>([]);
  const [expandedAlbumId, setExpandedAlbumId] = useState<string | null>(null);
  const [tracksByAlbum, setTracksByAlbum] = useState<Record<string, Track[]>>({});
  const [loadingAlbumId, setLoadingAlbumId] = useState<string | null>(null);

  useEffect(() => {
    getAlbums()
      .then(setAlbums)
      .catch(() => {
        // leave the list empty -- nothing else to fall back to yet
      });
  }, []);

  async function toggleAlbum(album: Album) {
    if (expandedAlbumId === album.id) {
      setExpandedAlbumId(null);
      return;
    }
    setExpandedAlbumId(album.id);
    if (tracksByAlbum[album.id]) return;

    setLoadingAlbumId(album.id);
    try {
      const tracks = await getAlbumTracks(album.id);
      setTracksByAlbum((prev) => ({ ...prev, [album.id]: tracks }));
    } catch {
      // stays uncached -- expanding again retries the fetch
    } finally {
      setLoadingAlbumId(null);
    }
  }

  async function handlePlayTrack(uri: string) {
    try {
      await playTrack(uri);
    } catch {
      // real state arrives over the WebSocket regardless of this promise
    }
  }

  return (
    <aside className="border-r border-neutral-800 p-4 overflow-y-auto">
      <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-3">Library</h2>
      <ul className="flex flex-col gap-1">
        {albums.map((album) => (
          <li key={album.id}>
            <button
              onClick={() => toggleAlbum(album)}
              className="w-full text-left px-2 py-1.5 rounded hover:bg-neutral-800 transition-colors"
            >
              <p className="text-sm font-medium truncate">{album.name}</p>
              <p className="text-xs text-neutral-400 truncate">{album.artist}</p>
            </button>

            {expandedAlbumId === album.id && (
              <ul className="ml-2 border-l border-neutral-800 pl-2 mb-2">
                {loadingAlbumId === album.id && <li className="text-xs text-neutral-500 py-1">Loading…</li>}
                {tracksByAlbum[album.id]?.map((track) => {
                  const isCurrent = currentTrack?.id === track.id;
                  return (
                    <li key={track.id}>
                      <button
                        onClick={() => handlePlayTrack(track.uri)}
                        className={`w-full text-left px-2 py-1 rounded text-sm truncate hover:bg-neutral-800 transition-colors ${
                          isCurrent ? 'text-neutral-100 font-medium' : 'text-neutral-300'
                        }`}
                      >
                        {track.track_number}. {track.title}{' '}
                        <span className="text-neutral-500">{formatDuration(track.length_ms)}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </aside>
  );
}
