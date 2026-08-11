import { useLiveState } from './lib/liveState';
import NowPlaying from './components/NowPlaying';

export default function App() {
  const { connected } = useLiveState();

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 font-sans">
      {!connected && <p className="text-center text-sm text-red-400 py-1">Reconnecting…</p>}
      <NowPlaying />
    </div>
  );
}
