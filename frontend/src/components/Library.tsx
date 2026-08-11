import { useEffect, useState } from 'react';
import { useLiveState } from '../lib/liveState';
import { getAlbumTracks, getAlbums, playTrack, type Album, type Track } from '../lib/api';
import { formatDuration } from '../lib/format';
import PlaybackBar from './PlaybackBar';

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
    <aside className="bg-base-900 h-full flex flex-col">
      <div className="flex-1 overflow-y-auto pt-14 px-5 pb-5">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-ink-muted mb-3">Library</h2>
        <ul className="flex flex-col gap-1">
          {albums.map((album) => {
            const isExpanded = expandedAlbumId === album.id;
            return (
              <li key={album.id}>
                <button
                  onClick={() => toggleAlbum(album)}
                  className={`w-full text-left px-3 py-2 rounded-lg transition-colors ${
                    isExpanded ? 'bg-base-800' : 'hover:bg-base-800'
                  }`}
                >
                  <p className="text-sm font-medium text-ink truncate">{album.name}</p>
                  <p className="text-xs text-ink-muted truncate">{album.artist}</p>
                </button>

                {isExpanded && (
                  <ul className="ml-3 border-l border-base-700 pl-3 mt-1 mb-2 flex flex-col gap-0.5">
                    {loadingAlbumId === album.id && (
                      <li className="text-xs text-ink-muted py-1.5">Loading…</li>
                    )}
                    {tracksByAlbum[album.id]?.map((track) => {
                      const isCurrent = currentTrack?.id === track.id;
                      return (
                        <li key={track.id}>
                          <button
                            onClick={() => handlePlayTrack(track.uri)}
                            className={`w-full flex items-baseline gap-2 text-left px-2 py-1.5 rounded-md text-sm transition-colors hover:bg-base-800 ${
                              isCurrent ? 'text-accent font-medium' : 'text-ink-muted'
                            }`}
                          >
                            <span className="truncate flex-1">
                              {track.track_number}. {track.title}
                            </span>
                            <span className="text-xs tabular-nums shrink-0">{formatDuration(track.length_ms)}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </div>
      <PlaybackBar />
    </aside>
  );
}
