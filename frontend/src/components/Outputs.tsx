import { useCallback, useEffect, useState } from 'react';
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
    <aside className="border-l border-neutral-800 p-4 flex flex-col gap-6 overflow-y-auto">
      <div>
        <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-2">Volume</h2>
        <VolumeSlider value={player?.volume ?? 0} onChange={(v) => setMasterVolume(v).catch(() => {})} />
      </div>

      <div className="min-w-0">
        <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-2">AirPlay devices</h2>
        <ul className="flex flex-col gap-3">
          {outputs.map((output) => (
            <li key={output.id} className="flex flex-col gap-1">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={output.selected}
                  onChange={() => toggleOutput(output)}
                  className="accent-neutral-100"
                />
                <span className="truncate flex-1">{output.name}</span>
                <span className="text-xs text-neutral-500 shrink-0">{output.type}</span>
              </label>
              {output.selected && (
                <VolumeSlider value={output.volume} onChange={(v) => changeOutputVolume(output, v)} />
              )}
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
