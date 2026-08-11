import { useEffect, useState } from 'react';
import { useLiveState } from '../lib/liveState';
import { playerCommand } from '../lib/api';
import { NextIcon, PauseIcon, PlayIcon, PrevIcon, SpinnerIcon } from './icons';

type PendingButton = 'prev' | 'playPause' | 'next' | null;

export default function NowPlaying() {
  const { player, currentTrack } = useLiveState();
  const [pending, setPending] = useState<PendingButton>(null);
  const [artworkFailed, setArtworkFailed] = useState(false);

  const isPlaying = player?.state === 'play';
  const artworkUrl = currentTrack ? `/api/artwork/item/${currentTrack.id}` : null;

  // A new track means any previous artwork failure no longer applies.
  useEffect(() => {
    setArtworkFailed(false);
  }, [artworkUrl]);

  async function handle(button: Exclude<PendingButton, null>, cmd: Parameters<typeof playerCommand>[0]) {
    if (pending) return;
    setPending(button);
    try {
      await playerCommand(cmd);
    } catch {
      // The command may still have taken effect server-side even if this
      // request failed/timed out client-side — the next state push over
      // the WebSocket is the source of truth, not this promise.
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="flex flex-col items-center gap-6 px-6 py-10 max-w-sm mx-auto">
      <div className="w-64 h-64 rounded-lg overflow-hidden bg-neutral-800 flex items-center justify-center shrink-0">
        {artworkUrl && !artworkFailed ? (
          <img
            key={artworkUrl}
            src={artworkUrl}
            alt=""
            className="w-full h-full object-cover"
            onError={() => setArtworkFailed(true)}
          />
        ) : (
          <span className="text-neutral-500 text-sm">No artwork</span>
        )}
      </div>

      <div className="text-center min-w-0 w-full">
        <p className="text-lg font-semibold truncate">{currentTrack?.title ?? 'Nothing playing'}</p>
        <p className="text-neutral-400 truncate">{currentTrack?.artist ?? ''}</p>
      </div>

      <div className="flex items-center gap-8">
        <button
          onClick={() => handle('prev', 'previous')}
          disabled={pending !== null}
          aria-label="Previous track"
          className="text-neutral-200 disabled:opacity-40"
        >
          <PrevIcon className="w-7 h-7" />
        </button>

        <button
          onClick={() => handle('playPause', isPlaying ? 'pause' : 'play')}
          disabled={pending !== null}
          aria-label={isPlaying ? 'Pause' : 'Play'}
          className="w-16 h-16 rounded-full bg-neutral-100 text-neutral-900 flex items-center justify-center disabled:opacity-40"
        >
          {pending === 'playPause' ? (
            <SpinnerIcon className="w-7 h-7" />
          ) : isPlaying ? (
            <PauseIcon className="w-7 h-7" />
          ) : (
            <PlayIcon className="w-7 h-7 translate-x-0.5" />
          )}
        </button>

        <button
          onClick={() => handle('next', 'next')}
          disabled={pending !== null}
          aria-label="Next track"
          className="text-neutral-200 disabled:opacity-40"
        >
          <NextIcon className="w-7 h-7" />
        </button>
      </div>
    </section>
  );
}
