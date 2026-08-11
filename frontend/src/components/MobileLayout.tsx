import { useState, type ReactNode } from 'react';
import Library from './Library';
import NowPlaying from './NowPlaying';
import Outputs from './Outputs';
import { AirPlayIcon, DiscIcon, LibraryIcon } from './icons';

type MobileTab = 'library' | 'now-playing' | 'outputs';

const TABS: { id: MobileTab; label: string; icon: (className: string) => ReactNode }[] = [
  { id: 'library', label: 'Library', icon: (c) => <LibraryIcon className={c} /> },
  { id: 'now-playing', label: 'Now Playing', icon: (c) => <DiscIcon className={c} /> },
  { id: 'outputs', label: 'Devices', icon: (c) => <AirPlayIcon className={c} /> }
];

export default function MobileLayout() {
  const [tab, setTab] = useState<MobileTab>('now-playing');

  return (
    <div className="h-screen flex flex-col bg-base-950 text-ink font-sans safe-top">
      <div className="flex-1 min-h-0 overflow-y-auto">
        {tab === 'library' && <Library topPadding="pt-5" />}
        {tab === 'now-playing' && <NowPlaying />}
        {tab === 'outputs' && <Outputs topPadding="pt-5" />}
      </div>

      <nav className="shrink-0 flex items-stretch border-t border-base-800 bg-base-900 safe-bottom">
        {TABS.map(({ id, label, icon }) => {
          const active = tab === id;
          return (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex-1 flex flex-col items-center gap-1 py-2.5 transition-colors ${
                active ? 'text-accent' : 'text-ink-muted'
              }`}
            >
              {icon('w-6 h-6')}
              <span className="text-[11px] font-medium">{label}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}
