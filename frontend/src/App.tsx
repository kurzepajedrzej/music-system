import { useLiveState } from './lib/liveState';

export default function App() {
  const { connected, player, cd } = useLiveState();

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100 p-6 font-sans">
      <h1 className="text-xl font-semibold mb-4">Music</h1>

      <p className="mb-4">
        WebSocket:{' '}
        <span className={connected ? 'text-green-400' : 'text-red-400'}>
          {connected ? 'connected' : 'disconnected'}
        </span>
      </p>

      <section className="mb-4">
        <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-1">Player</h2>
        <pre className="text-sm bg-neutral-900 rounded p-3 overflow-x-auto">
          {player ? JSON.stringify(player, null, 2) : 'no data yet'}
        </pre>
      </section>

      <section>
        <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-1">CD</h2>
        <pre className="text-sm bg-neutral-900 rounded p-3 overflow-x-auto">
          {cd ? JSON.stringify(cd, null, 2) : 'no data yet'}
        </pre>
      </section>
    </main>
  );
}
