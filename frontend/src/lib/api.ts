export type PlayerCommand = 'play' | 'pause' | 'stop' | 'next' | 'previous';

export async function playerCommand(cmd: PlayerCommand): Promise<void> {
  const res = await fetch(`/api/player/${cmd}`, { method: 'PUT' });
  if (!res.ok) {
    throw new Error(`player ${cmd} failed: ${res.status}`);
  }
}
