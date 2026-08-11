export type PlayerCommand = 'play' | 'pause' | 'stop' | 'next' | 'previous';

export async function playerCommand(cmd: PlayerCommand): Promise<void> {
  const res = await fetch(`/api/player/${cmd}`, { method: 'PUT' });
  if (!res.ok) {
    throw new Error(`player ${cmd} failed: ${res.status}`);
  }
}

export type CdCommand = 'play' | 'pause' | 'stop' | 'next' | 'prev';

export async function cdCommand(cmd: CdCommand): Promise<void> {
  const res = await fetch(`/api/cd/${cmd}`, { method: 'POST' });
  if (!res.ok) {
    throw new Error(`cd ${cmd} failed: ${res.status}`);
  }
}

export type SourceTarget = 'cd' | 'library';

export async function switchSource(target: SourceTarget): Promise<void> {
  const res = await fetch(`/api/source/${target}`, { method: 'POST' });
  if (!res.ok) {
    throw new Error(`switch to ${target} failed: ${res.status}`);
  }
}
