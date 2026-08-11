import { useEffect, useState } from 'react';
import { useDebouncedCallback } from '../lib/useDebouncedCallback';

export default function VolumeSlider({
  value,
  onChange,
  label
}: {
  value: number;
  onChange: (volume: number) => void;
  label?: string;
}) {
  const [local, setLocal] = useState(value);
  const debouncedOnChange = useDebouncedCallback(onChange, 200);

  // Follow external updates (WS push, poll refresh) except while the user
  // is mid-drag would be nicer, but for now this is a simple last-write
  // sync -- rare to collide with someone else adjusting the same slider.
  useEffect(() => {
    setLocal(value);
  }, [value]);

  return (
    <div className="flex items-center gap-2">
      {label && <span className="text-xs text-neutral-400 w-20 truncate shrink-0">{label}</span>}
      <input
        type="range"
        min={0}
        max={100}
        value={local}
        onChange={(e) => {
          const v = Number(e.target.value);
          setLocal(v);
          debouncedOnChange(v);
        }}
        className="flex-1 accent-neutral-100"
      />
      <span className="text-xs text-neutral-400 w-7 text-right shrink-0">{local}</span>
    </div>
  );
}
