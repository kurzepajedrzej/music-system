<script>
	import { artworkUrl } from '$lib/api/owntone.js';

	let { items = [], currentItemId = null, onJump = null, onRemove = null } = $props();

	function fmt(ms) {
		if (!ms) return '—';
		const s = Math.floor(ms / 1000);
		return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
	}

	function onImgError(e) {
		e.target.style.display = 'none';
		e.target.nextElementSibling?.classList.remove('hidden');
	}
</script>

<div class="flex flex-col gap-3 px-4 py-4">

	<p class="text-[11px] font-semibold tracking-[0.2em] uppercase text-base-content/35 px-1 mb-1">
		Queue{items.length ? ` — ${items.length} tracks` : ''}
	</p>

	{#if items.length === 0}
		<p class="text-center text-base-content/25 py-16 text-sm">Queue is empty</p>

	{:else}
		<div class="bg-base-200 rounded-2xl overflow-hidden shadow-sm">
			{#each items as item, i (item.id)}
				<div class="flex items-center gap-3 px-3 py-2.5
					{item.id === currentItemId ? 'bg-primary/8 border-l-2 border-primary' : ''}
					{i < items.length - 1 ? 'border-b border-base-content/6' : ''}">

					<!-- Artwork -->
					<div class="w-9 h-9 rounded-lg overflow-hidden flex-shrink-0 bg-base-300 flex items-center justify-center">
						{#if item.album_id}
							<img src={artworkUrl(item.album_id, 80)} alt="" class="w-full h-full object-cover" onerror={onImgError} />
							<span class="hidden text-base-content/20">
								<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
									<path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
								</svg>
							</span>
						{:else}
							<svg class="w-4 h-4 text-base-content/20" viewBox="0 0 24 24" fill="currentColor">
								<path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
							</svg>
						{/if}
					</div>

					<!-- Info (clickable to jump) -->
					<button onclick={() => onJump?.(item)} class="flex-1 min-w-0 text-left hover:opacity-75 transition-opacity">
						<p class="text-sm truncate {item.id === currentItemId ? 'font-semibold text-primary' : 'text-base-content'}">
							{item.title ?? 'Unknown'}
						</p>
						<p class="text-[11px] text-base-content/45 truncate">{item.artist ?? ''}</p>
					</button>

					<!-- Duration -->
					<span class="text-[11px] text-base-content/30 tabular-nums flex-shrink-0">{fmt(item.length_ms)}</span>

					<!-- Remove (hidden for currently playing item) -->
					{#if item.id !== currentItemId}
					<button
						onclick={() => onRemove?.(item)}
						class="w-7 h-7 flex items-center justify-center rounded-full flex-shrink-0
							text-base-content/20 hover:text-error hover:bg-error/10 transition-colors"
						aria-label="Remove from queue">
						<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
							<path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
						</svg>
					</button>
					{/if}

				</div>
			{/each}
		</div>
	{/if}

</div>
