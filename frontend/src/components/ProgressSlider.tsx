import { useState } from 'react';
import { formatDuration } from '../lib/format';

export default function ProgressSlider({
  positionMs,
  durationMs,
  onSeek
}: {
  positionMs: number;
  durationMs: number;
  onSeek: (positionMs: number) => void;
}) {
  const [dragValue, setDragValue] = useState<number | null>(null);

  // While dragging, ignore the live tick updates that arrive over the
  // WebSocket every second -- otherwise the thumb jumps out from under the
  // user's finger mid-drag. Only commits (calls onSeek) on release, not on
  // every intermediate value, matching how a seek bar is expected to behave.
  const displayValue = dragValue ?? positionMs;

  function commit() {
    if (dragValue !== null) {
      onSeek(dragValue);
      setDragValue(null);
    }
  }

  return (
    <div className="w-full flex items-center gap-2">
      <span className="text-xs text-ink-muted tabular-nums w-9 text-right shrink-0">
        {formatDuration(displayValue)}
      </span>
      <input
        type="range"
        min={0}
        max={Math.max(durationMs, 1)}
        value={displayValue}
        disabled={durationMs <= 0}
        onChange={(e) => setDragValue(Number(e.target.value))}
        onMouseUp={commit}
        onTouchEnd={commit}
        className="slim flex-1"
      />
      <span className="text-xs text-ink-muted tabular-nums w-9 shrink-0">{formatDuration(durationMs)}</span>
    </div>
  );
}
