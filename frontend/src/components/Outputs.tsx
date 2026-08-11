import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLiveState } from '../lib/liveState';
import { getOutputs, setMasterVolume, setOutput, type Output } from '../lib/api';
import VolumeSlider from './VolumeSlider';

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
    <aside className="bg-base-900 p-5 flex flex-col gap-7 overflow-y-auto h-full">
      {/* Master volume only means something once it has more than one
          speaker to balance -- with 0 or 1 selected, that speaker's own
          slider below already is the volume control. */}
      {selectedCount >= 2 && (
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-widest text-accent mb-3">Volume</h2>
          <VolumeSlider value={player?.volume ?? 0} onChange={(v) => setMasterVolume(v).catch(() => {})} />
        </div>
      )}

      <div className="min-w-0">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-accent mb-3">AirPlay</h2>
        <ul className="flex flex-col gap-1.5">
          {outputs.map((output) => (
            <li
              key={output.id}
              className={`rounded-lg px-3 py-2.5 transition-colors ${output.selected ? 'bg-base-800' : ''}`}
            >
              <label className="flex items-center gap-3 text-sm cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={output.selected}
                  onChange={() => toggleOutput(output)}
                  className="accent-accent w-4 h-4 shrink-0"
                />
                <span className="truncate flex-1 text-ink">{output.name}</span>
              </label>
              {output.selected && (
                <div className="mt-2 pl-7">
                  <VolumeSlider value={output.volume} onChange={(v) => changeOutputVolume(output, v)} />
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
