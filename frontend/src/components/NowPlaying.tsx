import { useEffect, useState } from 'react';
import { useLiveState } from '../lib/liveState';
import { cdCommand, playerCommand, switchSource } from '../lib/api';
import { NextIcon, PauseIcon, PlayIcon, PrevIcon, SpinnerIcon } from './icons';

type PendingButton = 'prev' | 'playPause' | 'next' | null;

const CD_STATE_LABELS: Record<string, string> = {
  playing: 'Playing',
  paused: 'Paused',
  stopped: 'Stopped',
  no_disc: 'No disc',
  tray_open: 'Tray open',
  changing: 'Changing disc…',
  seeking: 'Seeking…',
  searching_forward: 'Searching…',
  searching_backward: 'Searching…',
  powered_off: 'Powered off'
};

export default function NowPlaying() {
  const { player, currentTrack, cd } = useLiveState();
  const [pending, setPending] = useState<PendingButton>(null);
  const [sourcePending, setSourcePending] = useState(false);
  const [artworkFailed, setArtworkFailed] = useState(false);

  // The pipe queue item is what routers/source.py's switch_to_cd() queues
  // up — as long as it's the current item, we're on the CD source,
  // regardless of whether the physical player itself is playing/paused
  // right now (that's a separate signal: `cd.state`, not `player.state`).
  const isCdSource = currentTrack?.data_kind === 'pipe';
  const isPlaying = isCdSource ? cd?.state === 'playing' : player?.state === 'play';
  const artworkUrl = !isCdSource && currentTrack ? `/api/artwork/item/${currentTrack.id}` : null;
  const controlsDisabled = pending !== null || sourcePending;

  useEffect(() => {
    setArtworkFailed(false);
  }, [artworkUrl]);

  async function handleTransport(button: Exclude<PendingButton, null>) {
    if (controlsDisabled) return;
    setPending(button);
    try {
      if (isCdSource) {
        await cdCommand(button === 'playPause' ? (isPlaying ? 'pause' : 'play') : button === 'prev' ? 'prev' : 'next');
      } else {
        await playerCommand(
          button === 'playPause' ? (isPlaying ? 'pause' : 'play') : button === 'prev' ? 'previous' : 'next'
        );
      }
    } catch {
      // The command may still have taken effect server-side even if this
      // request failed/timed out client-side — the next state push over
      // the WebSocket is the source of truth, not this promise.
    } finally {
      setPending(null);
    }
  }

  async function handleSwitchSource(target: 'cd' | 'library') {
    const alreadyThere = target === 'cd' ? isCdSource : !isCdSource;
    if (controlsDisabled || alreadyThere) return;
    setSourcePending(true);
    try {
      await switchSource(target);
    } catch {
      // same reasoning as handleTransport — WS state push corrects this.
    } finally {
      setSourcePending(false);
    }
  }

  const title = isCdSource ? (cd?.disc_present ? `Track ${cd.track}` : 'CD') : (currentTrack?.title ?? 'Nothing playing');
  const subtitle = isCdSource ? (cd ? (CD_STATE_LABELS[cd.state] ?? cd.state) : '') : (currentTrack?.artist ?? '');

  return (
    <section className="flex flex-col items-center gap-6 px-6 py-10 max-w-sm mx-auto">
      <div className="flex rounded-full bg-neutral-800 p-1 text-sm">
        <button
          onClick={() => handleSwitchSource('library')}
          disabled={controlsDisabled}
          className={`px-4 py-1.5 rounded-full transition-colors disabled:opacity-40 ${
            !isCdSource ? 'bg-neutral-100 text-neutral-900' : 'text-neutral-300'
          }`}
        >
          Library
        </button>
        <button
          onClick={() => handleSwitchSource('cd')}
          disabled={controlsDisabled}
          className={`px-4 py-1.5 rounded-full transition-colors disabled:opacity-40 ${
            isCdSource ? 'bg-neutral-100 text-neutral-900' : 'text-neutral-300'
          }`}
        >
          CD
        </button>
      </div>

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
          <span className="text-neutral-500 text-sm">{isCdSource ? 'CD' : 'No artwork'}</span>
        )}
      </div>

      <div className="text-center min-w-0 w-full">
        <p className="text-lg font-semibold truncate">{title}</p>
        <p className="text-neutral-400 truncate">{subtitle}</p>
      </div>

      <div className="flex items-center gap-8">
        <button
          onClick={() => handleTransport('prev')}
          disabled={controlsDisabled}
          aria-label="Previous track"
          className="text-neutral-200 disabled:opacity-40"
        >
          <PrevIcon className="w-7 h-7" />
        </button>

        <button
          onClick={() => handleTransport('playPause')}
          disabled={controlsDisabled}
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
          onClick={() => handleTransport('next')}
          disabled={controlsDisabled}
          aria-label="Next track"
          className="text-neutral-200 disabled:opacity-40"
        >
          <NextIcon className="w-7 h-7" />
        </button>
      </div>
    </section>
  );
}
