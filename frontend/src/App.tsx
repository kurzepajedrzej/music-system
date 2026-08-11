import { useLiveState } from './lib/liveState';
import NowPlaying from './components/NowPlaying';
import Library from './components/Library';
import Outputs from './components/Outputs';

export default function App() {
  const { connected } = useLiveState();

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 font-sans">
      {!connected && <p className="text-center text-sm text-red-400 py-1">Reconnecting…</p>}
      <div className="grid grid-cols-[280px_1fr_280px] min-h-screen">
        <Library />
        <NowPlaying />
        <Outputs />
      </div>
    </div>
  );
}
