import { useState } from 'react';
import { useLiveState } from '../lib/liveState';
import { cdCommand, selectCdDisc, selectCdTrack } from '../lib/api';
import {
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  EjectIcon,
  PowerIcon,
  RepeatIcon,
  ShuffleIcon,
  StopIcon
} from './icons';

const quickButtonClass =
  'w-10 h-10 rounded-full bg-base-800 text-ink-muted flex items-center justify-center hover:text-ink transition-colors disabled:opacity-40';

export default function CdControls({ disabled }: { disabled: boolean }) {
  const { cd } = useLiveState();
  const [pending, setPending] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [trackInput, setTrackInput] = useState('');

  const isCdOff = cd?.state === 'powered_off';
  const busy = disabled || pending !== null;

  async function run(tag: string, action: () => Promise<void>) {
    if (busy) return;
    setPending(tag);
    try {
      await action();
    } catch {
      // real state arrives over the WebSocket regardless of this promise
    } finally {
      setPending(null);
    }
  }

  async function handleGoToTrack() {
    const n = Number(trackInput);
    if (!Number.isInteger(n) || n < 1 || n > 99) return;
    await run('track', () => selectCdTrack(n));
    setTrackInput('');
  }

  return (
    <div className="w-full flex flex-col items-center gap-3">
      <div className="flex items-center gap-2">
        <button
          onClick={() => run('disc-prev', () => cdCommand('disc-prev'))}
          disabled={busy}
          aria-label="Previous disc"
          className={quickButtonClass}
        >
          <ChevronLeftIcon className="w-4 h-4" />
        </button>
        <button
          onClick={() => run('open-close', () => cdCommand('open-close'))}
          disabled={busy}
          aria-label="Open or close tray"
          className={quickButtonClass}
        >
          <EjectIcon className="w-4 h-4" />
        </button>
        <button
          onClick={() => run('stop', () => cdCommand('stop'))}
          disabled={busy}
          aria-label="Stop"
          className={quickButtonClass}
        >
          <StopIcon className="w-4 h-4" />
        </button>
        <button
          onClick={() => run('repeat', () => cdCommand('repeat'))}
          disabled={busy}
          aria-label="Toggle repeat"
          className={quickButtonClass}
        >
          <RepeatIcon className="w-4 h-4" />
        </button>
        <button
          onClick={() => run('random', () => cdCommand('random'))}
          disabled={busy}
          aria-label="Toggle random"
          className={quickButtonClass}
        >
          <ShuffleIcon className="w-4 h-4" />
        </button>
        <button
          onClick={() => run('disc-next', () => cdCommand('disc-next'))}
          disabled={busy}
          aria-label="Next disc"
          className={quickButtonClass}
        >
          <ChevronRightIcon className="w-4 h-4" />
        </button>
        <button
          onClick={() => run(isCdOff ? 'power-on' : 'power-off', () => cdCommand(isCdOff ? 'power-on' : 'power-off'))}
          disabled={busy}
          aria-label={isCdOff ? 'Turn CD player on' : 'Turn CD player off'}
          className={`w-10 h-10 rounded-full flex items-center justify-center transition-colors disabled:opacity-40 ml-2 ${
            isCdOff ? 'bg-base-800 text-ink-muted hover:text-ink' : 'bg-accent text-base-950'
          }`}
        >
          <PowerIcon className="w-4 h-4" />
        </button>
      </div>

      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1 text-xs text-ink-muted hover:text-ink transition-colors"
      >
        {expanded ? 'Fewer controls' : 'More controls'}
        <ChevronDownIcon className={`w-3.5 h-3.5 transition-transform ${expanded ? 'rotate-180' : ''}`} />
      </button>

      {expanded && (
        <div className="w-full flex flex-col gap-4 pt-1">
          <div>
            {/* Real hardware doesn't report which disc is currently loaded
                (only the track within it), so unlike Power there's no way
                to highlight the active one here. */}
            <p className="text-xs font-semibold uppercase tracking-widest text-ink-muted mb-2">Disc</p>
            <div className="flex gap-2">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  onClick={() => run(`disc-${n}`, () => selectCdDisc(n))}
                  disabled={busy}
                  className="flex-1 h-10 rounded-lg bg-base-800 text-ink-muted hover:text-ink transition-colors disabled:opacity-40 text-sm font-medium"
                >
                  {n}
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-ink-muted mb-2">Scan</p>
            <div className="flex gap-2">
              <button
                onClick={() => run('search-backward', () => cdCommand('search-backward'))}
                disabled={busy}
                className={`flex-1 h-10 rounded-lg text-sm font-medium transition-colors disabled:opacity-40 ${
                  cd?.state === 'searching_backward' ? 'bg-accent text-base-950' : 'bg-base-800 text-ink-muted hover:text-ink'
                }`}
              >
                Scan −
              </button>
              <button
                onClick={() => run('search-forward', () => cdCommand('search-forward'))}
                disabled={busy}
                className={`flex-1 h-10 rounded-lg text-sm font-medium transition-colors disabled:opacity-40 ${
                  cd?.state === 'searching_forward' ? 'bg-accent text-base-950' : 'bg-base-800 text-ink-muted hover:text-ink'
                }`}
              >
                Scan +
              </button>
            </div>
            <p className="text-xs text-ink-muted mt-1.5">Stops when you press play, pause, or stop.</p>
          </div>

          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-ink-muted mb-2">Track</p>
            <div className="flex gap-2">
              <input
                type="number"
                min={1}
                max={99}
                inputMode="numeric"
                value={trackInput}
                onChange={(e) => setTrackInput(e.target.value)}
                placeholder="Track number"
                className="flex-1 h-10 px-3 rounded-lg bg-base-800 text-ink text-sm placeholder:text-ink-muted focus:outline-none focus:ring-1 focus:ring-accent"
              />
              <button
                onClick={handleGoToTrack}
                disabled={busy || !trackInput}
                className="px-4 h-10 rounded-lg bg-base-800 text-ink-muted hover:text-ink transition-colors disabled:opacity-40 text-sm font-medium"
              >
                Go
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
