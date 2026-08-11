import { useState } from 'react';
import { useLiveState } from './lib/liveState';
import NowPlaying from './components/NowPlaying';
import Library from './components/Library';
import Outputs from './components/Outputs';
import { SidebarLeftIcon, SidebarRightIcon } from './components/icons';

export default function App() {
  const { connected } = useLiveState();
  const [showLibrary, setShowLibrary] = useState(true);
  const [showOutputs, setShowOutputs] = useState(true);

  return (
    <div className="h-screen flex flex-col bg-base-950 text-ink font-sans">
      {!connected && <p className="text-center text-xs text-red-400 py-1 bg-base-900">Reconnecting…</p>}

      <header className="flex items-center justify-between px-4 py-3 border-b border-base-800 shrink-0">
        <button
          onClick={() => setShowLibrary((v) => !v)}
          aria-label="Toggle library panel"
          aria-pressed={showLibrary}
          className={`p-2 rounded-lg transition-colors ${showLibrary ? 'text-accent' : 'text-ink-muted hover:text-ink'}`}
        >
          <SidebarLeftIcon className="w-5 h-5" />
        </button>

        <h1 className="text-sm font-semibold tracking-wide text-ink-muted">Music</h1>

        <button
          onClick={() => setShowOutputs((v) => !v)}
          aria-label="Toggle outputs panel"
          aria-pressed={showOutputs}
          className={`p-2 rounded-lg transition-colors ${showOutputs ? 'text-accent' : 'text-ink-muted hover:text-ink'}`}
        >
          <SidebarRightIcon className="w-5 h-5" />
        </button>
      </header>

      <div
        className="flex-1 grid min-h-0 transition-[grid-template-columns] duration-200"
        style={{
          gridTemplateColumns: `${showLibrary ? '280px' : '0px'} 1fr ${showOutputs ? '280px' : '0px'}`,
          gridTemplateRows: '1fr'
        }}
      >
        <div className="min-w-0 overflow-hidden">{showLibrary && <Library />}</div>
        <div className="overflow-y-auto">
          <NowPlaying />
        </div>
        <div className="min-w-0 overflow-hidden">{showOutputs && <Outputs />}</div>
      </div>
    </div>
  );
}
