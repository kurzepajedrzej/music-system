import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLiveState } from '../lib/liveState';
import { getOutputs, setMasterVolume, setOutput, type Output } from '../lib/api';
import VolumeSlider from './VolumeSlider';
import Toggle from './Toggle';
import { AirPlayIcon } from './icons';

export default function Outputs() {
  const { player } = useLiveState();
  const [outputs, setOutputs] = useState<Output[]>([]);

  const refresh = useCallback(() => {
    getOutputs()
      .then(setOutputs)
      .catch(() => {
        // leave the last known list showing -- next poll retries
      });
  }, []);

  useEffect(() => {
    refresh();
    // Output selection/volume can change from another device -- there's no
    // WebSocket push for this yet, so poll for it.
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  const selectedCount = useMemo(() => outputs.filter((o) => o.selected).length, [outputs]);

  async function toggleOutput(output: Output) {
    const nextSelected = !output.selected;
    setOutputs((prev) => prev.map((o) => (o.id === output.id ? { ...o, selected: nextSelected } : o)));
    try {
      await setOutput(output.id, { selected: nextSelected });
    } catch {
      refresh();
    }
  }

  async function changeOutputVolume(output: Output, volume: number) {
    setOutputs((prev) => prev.map((o) => (o.id === output.id ? { ...o, volume } : o)));
    try {
      await setOutput(output.id, { volume });
    } catch {
      refresh();
    }
  }

  return (
    <aside className="bg-base-900 pt-14 px-5 pb-5 flex flex-col gap-7 overflow-y-auto h-full">
      {/* Master volume only means something once it has more than one
          speaker to balance -- with 0 or 1 selected, that speaker's own
          slider below already is the volume control. */}
      {selectedCount >= 2 && (
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-widest text-ink-muted mb-3">Volume</h2>
          <VolumeSlider value={player?.volume ?? 0} onChange={(v) => setMasterVolume(v).catch(() => {})} />
        </div>
      )}

      <div className="min-w-0">
        <AirPlayIcon className="w-5 h-5 text-ink-muted mb-3" />
        <ul className="flex flex-col gap-3">
          {outputs.map((output) => (
            <li key={output.id} className="rounded-lg px-3 py-2.5 bg-base-800/60">
              <div className="flex items-center gap-3">
                <span className="truncate flex-1 text-sm text-ink">{output.name}</span>
                <Toggle checked={output.selected} onChange={() => toggleOutput(output)} label={`Toggle ${output.name}`} />
              </div>
              <div className={`mt-2 transition-opacity ${output.selected ? '' : 'opacity-50'}`}>
                <VolumeSlider value={output.volume} onChange={(v) => changeOutputVolume(output, v)} />
              </div>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
