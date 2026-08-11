import { useEffect, useState } from 'react';
import { useLiveState } from '../lib/liveState';
import { cdCommand, playerCommand, seekTo, switchSource, type CdCommand } from '../lib/api';
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  DiscIcon,
  EjectIcon,
  NextIcon,
  PauseIcon,
  PlayIcon,
  PowerIcon,
  PrevIcon,
  RepeatIcon,
  ShuffleIcon,
  SpinnerIcon,
  StopIcon
} from './icons';
import ProgressSlider from './ProgressSlider';
import Queue from './Queue';

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
  const [cdActionPending, setCdActionPending] = useState<CdCommand | null>(null);
  const [artworkFailed, setArtworkFailed] = useState(false);

  // The pipe queue item is what routers/source.py's switch_to_cd() queues
  // up -- as long as it's the current item, we're on the CD source,
  // regardless of whether the physical player itself is playing/paused
  // right now (that's a separate signal: `cd.state`, not `player.state`).
  const isCdSource = currentTrack?.data_kind === 'pipe';
  const isPlaying = isCdSource ? cd?.state === 'playing' : player?.state === 'play';
  const isCdOff = cd?.state === 'powered_off';
  const artworkUrl = !isCdSource && currentTrack ? `/api/artwork/item/${currentTrack.id}` : null;
  const controlsDisabled = pending !== null || sourcePending;
  const cdActionsDisabled = controlsDisabled || cdActionPending !== null;

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
      // request failed/timed out client-side -- the next state push over
      // the WebSocket is the source of truth, not this promise.
    } finally {
      setPending(null);
    }
  }

  async function handleCdAction(cmd: CdCommand) {
    if (cdActionsDisabled) return;
    setCdActionPending(cmd);
    try {
      await cdCommand(cmd);
    } catch {
      // same reasoning as handleTransport -- WS state push corrects this.
    } finally {
      setCdActionPending(null);
    }
  }

  async function handleSwitchSource(target: 'cd' | 'library') {
    const alreadyThere = target === 'cd' ? isCdSource : !isCdSource;
    if (controlsDisabled || alreadyThere) return;
    setSourcePending(true);
    try {
      await switchSource(target);
    } catch {
      // same reasoning as handleTransport.
    } finally {
      setSourcePending(false);
    }
  }

  const title = isCdSource ? (cd?.disc_present ? `Track ${cd.track}` : 'CD') : (currentTrack?.title ?? 'Nothing playing');
  const subtitle = isCdSource ? (cd ? (CD_STATE_LABELS[cd.state] ?? cd.state) : '') : (currentTrack?.artist ?? '');

  // No progress bar for CD -- there's no reliable elapsed/duration reading
  // for physical CD audio (SerialController's elapsed_seconds/
  // track_duration_seconds are still hardcoded to 0, unlike OwnTone's
  // item_progress_ms/item_length_ms which the WebSocket tick keeps live).
  const showProgress = !isCdSource && !!currentTrack;

  async function handleSeek(positionMs: number) {
    try {
      await seekTo(positionMs);
    } catch {
      // real state arrives over the WebSocket regardless of this promise
    }
  }

  return (
    <section className="flex flex-col items-center gap-6 px-6 py-10 max-w-xl mx-auto">
      <div className="flex rounded-full bg-base-800 p-1 text-sm">
        <button
          onClick={() => handleSwitchSource('library')}
          disabled={controlsDisabled}
          className={`px-4 py-1.5 rounded-full font-medium transition-colors disabled:opacity-40 ${
            !isCdSource ? 'bg-accent text-base-950' : 'text-ink-muted'
          }`}
        >
          Library
        </button>
        <button
          onClick={() => handleSwitchSource('cd')}
          disabled={controlsDisabled}
          className={`px-4 py-1.5 rounded-full font-medium transition-colors disabled:opacity-40 ${
            isCdSource ? 'bg-accent text-base-950' : 'text-ink-muted'
          }`}
        >
          CD
        </button>
      </div>

      {/* CD audio has no cover art to source -- rather than an empty photo
          frame, CD mode gets a small disc mark instead of the full artwork
          box. */}
      {isCdSource ? (
        <DiscIcon className={`w-16 h-16 shrink-0 ${isPlaying ? 'text-accent' : 'text-ink-muted'}`} />
      ) : (
        <div className="w-72 h-72 rounded-2xl overflow-hidden bg-base-800 flex items-center justify-center shrink-0">
          {artworkUrl && !artworkFailed ? (
            <img
              key={artworkUrl}
              src={artworkUrl}
              alt=""
              className="w-full h-full object-cover"
              onError={() => setArtworkFailed(true)}
            />
          ) : (
            <span className="text-ink-muted text-sm">No artwork</span>
          )}
        </div>
      )}

      <div className="text-center min-w-0 w-full">
        <p className="text-lg font-semibold text-ink truncate">{title}</p>
        <div className="flex items-center justify-center gap-1.5 mt-0.5">
          <span
            className={`w-1.5 h-1.5 rounded-full shrink-0 ${isPlaying ? 'bg-green-500' : 'bg-ink-muted/50'}`}
            aria-hidden
          />
          <p className="text-ink-muted truncate">{subtitle}</p>
        </div>
      </div>

      {showProgress && (
        <ProgressSlider
          positionMs={player?.item_progress_ms ?? 0}
          durationMs={player?.item_length_ms ?? 0}
          onSeek={handleSeek}
        />
      )}

      <div className="flex items-center gap-8">
        <button
          onClick={() => handleTransport('prev')}
          disabled={controlsDisabled}
          aria-label="Previous track"
          className="p-2.5 -m-2.5 text-ink disabled:opacity-40"
        >
          <PrevIcon className="w-7 h-7" />
        </button>

        <button
          onClick={() => handleTransport('playPause')}
          disabled={controlsDisabled}
          aria-label={isPlaying ? 'Pause' : 'Play'}
          className="w-16 h-16 rounded-full bg-accent text-base-950 flex items-center justify-center disabled:opacity-40"
        >
          {pending === 'playPause' ? (
            <SpinnerIcon className="w-7 h-7" />
          ) : isPlaying ? (
            <PauseIcon className="w-7 h-7" />
          ) : (
            <PlayIcon className="w-7 h-7" />
          )}
        </button>

        <button
          onClick={() => handleTransport('next')}
          disabled={controlsDisabled}
          aria-label="Next track"
          className="p-2.5 -m-2.5 text-ink disabled:opacity-40"
        >
          <NextIcon className="w-7 h-7" />
        </button>
      </div>

      {isCdSource && (
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={() => handleCdAction('disc-prev')}
            disabled={cdActionsDisabled}
            aria-label="Previous disc"
            className="w-10 h-10 rounded-full bg-base-800 text-ink-muted flex items-center justify-center hover:text-ink transition-colors disabled:opacity-40"
          >
            <ChevronLeftIcon className="w-4 h-4" />
          </button>
          <button
            onClick={() => handleCdAction('open-close')}
            disabled={cdActionsDisabled}
            aria-label="Open or close tray"
            className="w-10 h-10 rounded-full bg-base-800 text-ink-muted flex items-center justify-center hover:text-ink transition-colors disabled:opacity-40"
          >
            <EjectIcon className="w-4 h-4" />
          </button>
          <button
            onClick={() => handleCdAction('stop')}
            disabled={cdActionsDisabled}
            aria-label="Stop"
            className="w-10 h-10 rounded-full bg-base-800 text-ink-muted flex items-center justify-center hover:text-ink transition-colors disabled:opacity-40"
          >
            <StopIcon className="w-4 h-4" />
          </button>
          <button
            onClick={() => handleCdAction('repeat')}
            disabled={cdActionsDisabled}
            aria-label="Toggle repeat"
            className="w-10 h-10 rounded-full bg-base-800 text-ink-muted flex items-center justify-center hover:text-ink transition-colors disabled:opacity-40"
          >
            <RepeatIcon className="w-4 h-4" />
          </button>
          <button
            onClick={() => handleCdAction('random')}
            disabled={cdActionsDisabled}
            aria-label="Toggle random"
            className="w-10 h-10 rounded-full bg-base-800 text-ink-muted flex items-center justify-center hover:text-ink transition-colors disabled:opacity-40"
          >
            <ShuffleIcon className="w-4 h-4" />
          </button>
          <button
            onClick={() => handleCdAction('disc-next')}
            disabled={cdActionsDisabled}
            aria-label="Next disc"
            className="w-10 h-10 rounded-full bg-base-800 text-ink-muted flex items-center justify-center hover:text-ink transition-colors disabled:opacity-40"
          >
            <ChevronRightIcon className="w-4 h-4" />
          </button>
          <button
            onClick={() => handleCdAction(isCdOff ? 'power-on' : 'power-off')}
            disabled={cdActionsDisabled}
            aria-label={isCdOff ? 'Turn CD player on' : 'Turn CD player off'}
            className={`w-10 h-10 rounded-full flex items-center justify-center transition-colors disabled:opacity-40 ml-2 ${
              isCdOff ? 'bg-base-800 text-ink-muted hover:text-ink' : 'bg-accent text-base-950'
            }`}
          >
            <PowerIcon className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* The queue is an OwnTone/Library concept -- CD audio has no queue. */}
      {!isCdSource && <Queue />}
    </section>
  );
}
