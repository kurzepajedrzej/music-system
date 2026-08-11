import { useState } from 'react';
import { useLiveState } from '../lib/liveState';
import { cdCommand, playerCommand } from '../lib/api';
import { PauseIcon, PlayIcon, SpinnerIcon } from './icons';

export default function PlaybackBar() {
  const { player, currentTrack, cd } = useLiveState();
  const [pending, setPending] = useState(false);

  const isCdSource = currentTrack?.data_kind === 'pipe';
  const isPlaying = isCdSource ? cd?.state === 'playing' : player?.state === 'play';
  const title = isCdSource ? (cd?.disc_present ? `CD · Track ${cd.track}` : 'CD') : (currentTrack?.title ?? 'Nothing playing');
  const subtitle = isCdSource ? '' : (currentTrack?.artist ?? '');

  async function togglePlayPause() {
    if (pending) return;
    setPending(true);
    try {
      if (isCdSource) {
        await cdCommand(isPlaying ? 'pause' : 'play');
      } else {
        await playerCommand(isPlaying ? 'pause' : 'play');
      }
    } catch {
      // WS push / status poll corrects this regardless of this promise
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="shrink-0 px-4 py-3 bg-base-800 border-t border-base-700 flex items-center gap-3">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink truncate">{title}</p>
        {subtitle && <p className="text-xs text-ink-muted truncate">{subtitle}</p>}
      </div>
      <button
        onClick={togglePlayPause}
        disabled={pending}
        aria-label={isPlaying ? 'Pause' : 'Play'}
        className="w-9 h-9 rounded-full bg-accent text-base-950 flex items-center justify-center shrink-0 disabled:opacity-40"
      >
        {pending ? (
          <SpinnerIcon className="w-4 h-4" />
        ) : isPlaying ? (
          <PauseIcon className="w-4 h-4" />
        ) : (
          <PlayIcon className="w-4 h-4 translate-x-0.5" />
        )}
      </button>
    </div>
  );
}
