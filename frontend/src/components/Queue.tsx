import { useLiveState } from '../lib/liveState';
import { playQueueItem, removeQueueItem } from '../lib/api';
import { formatDuration } from '../lib/format';
import { CloseIcon } from './icons';

export default function Queue() {
  const { queue, currentTrack } = useLiveState();

  // Only show what's actually coming up -- once a track has played (or been
  // skipped past), it drops out of this list. currentTrack itself is
  // excluded too since it's already shown in Now Playing above.
  const currentPosition = currentTrack?.position;
  const upcoming =
    typeof currentPosition === 'number' ? queue.filter((item) => (item.position ?? 0) > currentPosition) : [];

  async function handlePlayItem(itemId: number) {
    try {
      await playQueueItem(itemId);
    } catch {
      // real state arrives over the WebSocket regardless of this promise
    }
  }

  async function handleRemoveItem(itemId: number) {
    try {
      await removeQueueItem(itemId);
    } catch {
      // real state arrives over the WebSocket regardless of this promise
    }
  }

  if (upcoming.length === 0) {
    return null;
  }

  return (
    <div className="w-full">
      <h2 className="text-xs font-semibold uppercase tracking-widest text-ink-muted mb-3">Queue</h2>
      <ul className="flex flex-col gap-0.5">
        {upcoming.map((item) => (
          <li
            key={item.id}
            className="group flex items-center gap-3 px-3 py-2 rounded-lg transition-colors hover:bg-base-800"
          >
            <button onClick={() => handlePlayItem(item.id)} className="min-w-0 flex-1 text-left">
              <p className="text-sm text-ink truncate">{item.title}</p>
              <p className="text-xs text-ink-muted truncate">{item.artist}</p>
            </button>
            <span className="text-xs text-ink-muted tabular-nums shrink-0">
              {formatDuration(item.length_ms ?? 0)}
            </span>
            <button
              onClick={() => handleRemoveItem(item.id)}
              aria-label="Remove from queue"
              className="shrink-0 text-ink-muted hover:text-ink opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <CloseIcon className="w-4 h-4" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
