import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';

export interface QueueItem {
  id: number;
  position?: number;
  title?: string;
  artist?: string;
  album?: string;
  length_ms?: number;
  // "pipe" means this queue item is the raw CD/line-in audio feed
  // (behringer.pipe), not a real library track — see routers/source.py.
  data_kind?: string;
  [key: string]: unknown;
}

export interface Player {
  state: string;
  volume?: number;
  item_id?: number;
  item_progress_ms?: number;
  item_length_ms?: number;
  [key: string]: unknown;
}

export interface CdStatus {
  state: string;
  disc_present: boolean;
  track: number;
  total_tracks: number;
  elapsed_seconds: number;
  track_duration_seconds: number;
  degraded: boolean;
}

interface StateMessage {
  type: 'state';
  player: Player | null;
  queue: QueueItem[];
  currentTrack: QueueItem | null;
  cd: CdStatus;
  timestamp: number;
}

interface TickMessage {
  type: 'tick';
  position_ms: number | null;
  item_length_ms: number | null;
  state: string;
  timestamp: number;
}

interface CdMessage {
  type: 'cd';
  cd: CdStatus;
  timestamp: number;
}

type WsMessage = StateMessage | TickMessage | CdMessage;

export interface LiveState {
  connected: boolean;
  player: Player | null;
  queue: QueueItem[];
  currentTrack: QueueItem | null;
  cd: CdStatus | null;
}

const initialState: LiveState = {
  connected: false,
  player: null,
  queue: [],
  currentTrack: null,
  cd: null
};

const LiveStateContext = createContext<LiveState>(initialState);

export function useLiveState(): LiveState {
  return useContext(LiveStateContext);
}

export function LiveStateProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<LiveState>(initialState);
  const closedByCallerRef = useRef(false);

  useEffect(() => {
    closedByCallerRef.current = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function open() {
      const wsBase = location.origin.replace(/^http/, 'ws');
      socket = new WebSocket(`${wsBase}/api/ws`);

      socket.onopen = () => {
        setState((prev) => ({ ...prev, connected: true }));
      };

      socket.onclose = () => {
        setState((prev) => ({ ...prev, connected: false }));
        if (!closedByCallerRef.current) {
          reconnectTimer = setTimeout(open, 3000);
        }
      };

      socket.onmessage = (event) => {
        let msg: WsMessage;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }

        if (msg.type === 'state') {
          setState((prev) => ({
            ...prev,
            player: msg.player,
            queue: msg.queue,
            currentTrack: msg.currentTrack,
            cd: msg.cd
          }));
        } else if (msg.type === 'cd') {
          setState((prev) => ({ ...prev, cd: msg.cd }));
        } else if (msg.type === 'tick') {
          setState((prev) =>
            prev.player
              ? {
                  ...prev,
                  player: {
                    ...prev.player,
                    state: msg.state,
                    item_progress_ms: msg.position_ms ?? prev.player.item_progress_ms,
                    item_length_ms: msg.item_length_ms ?? prev.player.item_length_ms
                  }
                }
              : prev
          );
        }
      };
    }

    open();

    return () => {
      closedByCallerRef.current = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  useEffect(() => {
    // The WebSocket push above is the primary path for CD state, but CD
    // transitions (power on, disc changes) can take several real seconds,
    // and there's no guarantee every push lands (tab backgrounded, a brief
    // network drop, etc.). Reconciling against the real status directly
    // every few seconds means a missed push self-corrects quickly instead
    // of leaving the UI stuck on a stale state indefinitely.
    const interval = setInterval(() => {
      fetch('/api/cd/status')
        .then((res) => (res.ok ? res.json() : null))
        .then((cd) => {
          if (cd) setState((prev) => ({ ...prev, cd }));
        })
        .catch(() => {});
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  return <LiveStateContext.Provider value={state}>{children}</LiveStateContext.Provider>;
}
