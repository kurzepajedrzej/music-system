<script>
	import { onMount } from 'svelte';
	import { getAlbums, getAlbumTracks, clearAndPlay, addToQueue, artworkUrl, search as apiSearch } from '$lib/api/owntone.js';

	let { onPlay = null, onQueue = null } = $props();

	let albums = $state([]);
	let loading = $state(true);
	let error = $state(null);

	let selectedAlbum = $state(null);
	let tracks = $state([]);
	let tracksLoading = $state(false);
	let tracksError = $state(null);

	// Search
	let query = $state('');
	let searchResults = $state(null); // null = not searching
	let searchLoading = $state(false);
	let searchTimeout;

	$effect(() => {
		const q = query.trim();
		clearTimeout(searchTimeout);
		if (!q) { searchResults = null; return; }
		searchTimeout = setTimeout(async () => {
			searchLoading = true;
			try {
				const r = await apiSearch(q);
				searchResults = {
					tracks: r.tracks?.items ?? [],
					albums: r.albums?.items ?? []
				};
			} catch {
				searchResults = { tracks: [], albums: [] };
			} finally {
				searchLoading = false;
			}
		}, 400);
	});

	function formatDuration(ms) {
		if (!ms) return '—';
		const totalSec = Math.floor(ms / 1000);
		const m = Math.floor(totalSec / 60);
		const s = totalSec % 60;
		return `${m}:${s.toString().padStart(2, '0')}`;
	}

	async function loadAlbums() {
		loading = true;
		error = null;
		try {
			albums = await getAlbums();
		} catch {
			error = 'Cannot reach library';
		} finally {
			loading = false;
		}
	}

	async function openAlbum(album) {
		selectedAlbum = album;
		tracksLoading = true;
		tracksError = null;
		tracks = [];
		try {
			tracks = await getAlbumTracks(album.id);
		} catch {
			tracksError = 'Failed to load tracks';
		} finally {
			tracksLoading = false;
		}
	}

	function goBack() {
		selectedAlbum = null;
		tracks = [];
	}

	async function playTrack(track) {
		await clearAndPlay(`library:track:${track.id}`);
		onPlay?.(track);
	}

	async function playAlbum(album) {
		await clearAndPlay(`library:album:${album.id}`);
		onPlay?.(null);
	}

	async function queueTrack(e, track) {
		e.stopPropagation();
		await addToQueue(`library:track:${track.id}`);
		onQueue?.();
	}

	async function queueAlbum(e, album) {
		e.stopPropagation();
		await addToQueue(`library:album:${album.id}`);
		onQueue?.();
	}

	function onImgError(e) {
		e.target.style.display = 'none';
		e.target.nextElementSibling?.classList.remove('hidden');
	}

	onMount(loadAlbums);
</script>

<div class="flex flex-col gap-3 px-4 py-4">

	<!-- Search bar -->
	<div class="relative">
		<svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-base-content/30 pointer-events-none"
			viewBox="0 0 24 24" fill="currentColor">
			<path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
		</svg>
		<input
			type="text"
			placeholder="Search music…"
			bind:value={query}
			class="w-full pl-9 pr-9 py-2 rounded-xl bg-base-200 text-sm text-base-content
				placeholder:text-base-content/30 outline-none focus:ring-2 focus:ring-primary/30 transition-all"
		/>
		{#if query}
			<button
				onclick={() => query = ''}
				class="absolute right-3 top-1/2 -translate-y-1/2 text-base-content/30 hover:text-base-content/60 transition-colors">
				<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
					<path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
				</svg>
			</button>
		{/if}
	</div>

	<!-- ── Search results ──────────────────────────────────────────────── -->
	{#if query.trim()}

		{#if searchLoading}
			<div class="flex justify-center py-16">
				<div class="w-6 h-6 rounded-full border-2 border-primary/30 border-t-primary animate-spin"></div>
			</div>

		{:else if searchResults}
			{@const totalResults = (searchResults.tracks?.length ?? 0) + (searchResults.albums?.length ?? 0)}

			{#if totalResults === 0}
				<p class="text-center text-base-content/25 py-16 text-sm">No results for "{query}"</p>

			{:else}

				<!-- Track results -->
				{#if searchResults.tracks.length > 0}
					<p class="text-[11px] font-semibold tracking-[0.2em] uppercase text-base-content/35 px-1">Tracks</p>
					<div class="bg-base-200 rounded-2xl overflow-hidden shadow-sm">
						{#each searchResults.tracks as track, i (track.id)}
							<div class="flex items-center gap-3 px-4 py-3
								{i < searchResults.tracks.length - 1 ? 'border-b border-base-content/6' : ''}">

								<!-- Artwork -->
								<div class="w-9 h-9 rounded-lg overflow-hidden flex-shrink-0 bg-base-300 flex items-center justify-center">
									{#if track.album_id}
										<img src={artworkUrl(track.album_id, 80)} alt="" class="w-full h-full object-cover" onerror={onImgError} />
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

								<!-- Info -->
								<div class="flex-1 min-w-0">
									<p class="text-sm text-base-content truncate">{track.title ?? 'Unknown'}</p>
									<p class="text-[11px] text-base-content/45 truncate">{track.artist ?? ''}</p>
								</div>

								<!-- Duration -->
								<span class="text-[12px] text-base-content/35 flex-shrink-0 tabular-nums">
									{formatDuration(track.length_ms)}
								</span>

								<!-- Add to queue -->
								<button
									onclick={(e) => queueTrack(e, track)}
									class="w-7 h-7 flex items-center justify-center rounded-full flex-shrink-0
										text-base-content/30 hover:text-primary hover:bg-primary/10 transition-colors"
									title="Add to queue">
									<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
										<path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
									</svg>
								</button>

								<!-- Play -->
								<button
									onclick={() => playTrack(track)}
									class="w-7 h-7 flex items-center justify-center rounded-full flex-shrink-0
										bg-primary text-white hover:bg-primary/80 transition-colors"
									title="Play now">
									<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
										<path d="M8 5v14l11-7z"/>
									</svg>
								</button>

							</div>
						{/each}
					</div>
				{/if}

				<!-- Album results -->
				{#if searchResults.albums.length > 0}
					<p class="text-[11px] font-semibold tracking-[0.2em] uppercase text-base-content/35 px-1 mt-1">Albums</p>
					<div class="bg-base-200 rounded-2xl overflow-hidden shadow-sm">
						{#each searchResults.albums as album, i (album.id)}
							<div class="flex items-center gap-3 px-4 py-3
								{i < searchResults.albums.length - 1 ? 'border-b border-base-content/6' : ''}">

								<!-- Artwork + Info (opens album) -->
								<button onclick={() => { query = ''; openAlbum(album); }}
									class="flex items-center gap-3 flex-1 min-w-0 text-left hover:opacity-80 transition-opacity">
									<div class="w-11 h-11 rounded-lg overflow-hidden flex-shrink-0 bg-base-300 flex items-center justify-center">
										<img src={artworkUrl(album.id, 96)} alt="" class="w-full h-full object-cover" onerror={onImgError} />
										<span class="hidden text-base-content/20">
											<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
												<path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
											</svg>
										</span>
									</div>
									<div class="flex-1 min-w-0">
										<p class="text-sm font-medium text-base-content truncate">{album.name ?? 'Unknown Album'}</p>
										<p class="text-[12px] text-base-content/45 truncate">{album.artist ?? 'Unknown Artist'}</p>
									</div>
								</button>

								<!-- Add to queue -->
								<button onclick={(e) => queueAlbum(e, album)}
									class="w-7 h-7 flex items-center justify-center rounded-full flex-shrink-0
										text-base-content/30 hover:text-primary hover:bg-primary/10 transition-colors"
									title="Add to queue">
									<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
										<path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
									</svg>
								</button>

								<svg class="w-4 h-4 text-base-content/25 flex-shrink-0" viewBox="0 0 24 24" fill="currentColor">
									<path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/>
								</svg>
							</div>
						{/each}
					</div>
				{/if}

			{/if}
		{/if}

	<!-- ── Album / Track browser ───────────────────────────────────────── -->
	{:else if !selectedAlbum}

		<p class="text-[11px] font-semibold tracking-[0.2em] uppercase text-base-content/35 px-1 mb-1">Albums</p>

		{#if loading}
			<div class="flex justify-center py-16">
				<div class="w-6 h-6 rounded-full border-2 border-primary/30 border-t-primary animate-spin"></div>
			</div>

		{:else if error}
			<div class="bg-base-200 rounded-2xl p-4 flex items-center gap-3 shadow-sm">
				<div class="w-2 h-2 rounded-full bg-error flex-shrink-0"></div>
				<span class="text-sm text-base-content/50">{error}</span>
				<button onclick={loadAlbums} class="ml-auto text-xs text-primary hover:text-primary/70 transition-colors font-medium">Retry</button>
			</div>

		{:else if albums.length === 0}
			<p class="text-center text-base-content/25 py-16 text-sm">No albums found</p>

		{:else}
			<div class="bg-base-200 rounded-2xl overflow-hidden shadow-sm">
				{#each albums as album, i (album.id)}
					<div class="flex items-center gap-3 px-4 py-3
						{i < albums.length - 1 ? 'border-b border-base-content/6' : ''}">

						<!-- Artwork + Info (opens album) -->
						<button onclick={() => openAlbum(album)}
							class="flex items-center gap-3 flex-1 min-w-0 text-left hover:opacity-80 transition-opacity active:opacity-60">
							<div class="w-11 h-11 rounded-lg overflow-hidden flex-shrink-0 bg-base-300 flex items-center justify-center">
								<img src={artworkUrl(album.id, 96)} alt="" class="w-full h-full object-cover" onerror={onImgError} />
								<span class="hidden text-base-content/20">
									<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
										<path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
									</svg>
								</span>
							</div>
							<div class="flex-1 min-w-0">
								<p class="text-sm font-medium text-base-content truncate">{album.name ?? 'Unknown Album'}</p>
								<p class="text-[12px] text-base-content/45 truncate">{album.artist ?? 'Unknown Artist'}</p>
							</div>
						</button>

						<!-- Actions -->
						<div class="flex items-center gap-1 flex-shrink-0">
							<span class="text-[12px] text-base-content/30">{album.track_count ?? ''}</span>
							<button onclick={(e) => queueAlbum(e, album)}
								class="w-7 h-7 flex items-center justify-center rounded-full
									text-base-content/25 hover:text-primary hover:bg-primary/10 transition-colors"
								title="Add to queue">
								<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
									<path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
								</svg>
							</button>
							<svg class="w-4 h-4 text-base-content/25" viewBox="0 0 24 24" fill="currentColor">
								<path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/>
							</svg>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<button onclick={loadAlbums}
			class="flex items-center justify-center gap-1.5 text-[12px] text-base-content/30
				hover:text-base-content/50 transition-colors mt-1 py-2">
			<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
				<path d="M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
			</svg>
			Refresh
		</button>

	{:else}
		<!-- Track list -->
		<button
			onclick={goBack}
			class="flex items-center gap-1 text-[13px] text-primary font-medium hover:text-primary/70 transition-colors mb-1 px-1"
		>
			<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
				<path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/>
			</svg>
			Albums
		</button>

		<!-- Album header -->
		<div class="bg-base-200 rounded-2xl p-4 flex items-center gap-4 shadow-sm">
			<div class="w-16 h-16 rounded-xl overflow-hidden flex-shrink-0 bg-base-300 flex items-center justify-center">
				<img src={artworkUrl(selectedAlbum.id, 128)} alt="" class="w-full h-full object-cover" onerror={onImgError} />
				<span class="hidden text-base-content/20">
					<svg class="w-8 h-8" viewBox="0 0 24 24" fill="currentColor">
						<path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
					</svg>
				</span>
			</div>
			<div class="flex-1 min-w-0">
				<p class="text-sm font-semibold text-base-content truncate">{selectedAlbum.name ?? 'Unknown Album'}</p>
				<p class="text-[12px] text-base-content/45 truncate">{selectedAlbum.artist ?? 'Unknown Artist'}</p>
				<p class="text-[11px] text-base-content/30 mt-0.5">{selectedAlbum.track_count ?? tracks.length} tracks</p>
			</div>
			<!-- Add album to queue -->
			<button
				onclick={(e) => queueAlbum(e, selectedAlbum)}
				class="w-9 h-9 flex items-center justify-center rounded-full flex-shrink-0
					text-base-content/40 hover:text-primary hover:bg-primary/10 transition-colors"
				title="Add album to queue">
				<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
					<path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
				</svg>
			</button>
			<!-- Play album -->
			<button
				onclick={() => playAlbum(selectedAlbum)}
				class="flex-shrink-0 flex items-center justify-center w-10 h-10 rounded-full bg-primary text-white shadow-md shadow-primary/25 hover:bg-primary/90 transition-colors"
				aria-label="Play all"
			>
				<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
					<path d="M8 4v16l12-8z"/>
				</svg>
			</button>
		</div>

		<!-- Tracks -->
		{#if tracksLoading}
			<div class="flex justify-center py-10">
				<div class="w-6 h-6 rounded-full border-2 border-primary/30 border-t-primary animate-spin"></div>
			</div>

		{:else if tracksError}
			<div class="bg-base-200 rounded-2xl p-4 flex items-center gap-3 shadow-sm">
				<div class="w-2 h-2 rounded-full bg-error flex-shrink-0"></div>
				<span class="text-sm text-base-content/50">{tracksError}</span>
			</div>

		{:else if tracks.length === 0}
			<p class="text-center text-base-content/25 py-10 text-sm">No tracks found</p>

		{:else}
			<div class="bg-base-200 rounded-2xl overflow-hidden shadow-sm">
				{#each tracks as track, i (track.id)}
					<div class="flex items-center gap-3 px-4 py-3
						{i < tracks.length - 1 ? 'border-b border-base-content/6' : ''}">

						<!-- Track number -->
						<span class="text-[12px] text-base-content/30 w-5 text-right flex-shrink-0 tabular-nums">
							{track.track_number ?? i + 1}
						</span>

						<!-- Title (clickable to play) -->
						<button onclick={() => playTrack(track)} class="flex-1 min-w-0 text-left hover:opacity-75 transition-opacity">
							<p class="text-sm text-base-content truncate">{track.title ?? 'Unknown'}</p>
						</button>

						<!-- Duration -->
						<span class="text-[12px] text-base-content/35 flex-shrink-0 tabular-nums">
							{formatDuration(track.length_ms)}
						</span>

						<!-- Add to queue -->
						<button
							onclick={(e) => queueTrack(e, track)}
							class="w-7 h-7 flex items-center justify-center rounded-full flex-shrink-0
								text-base-content/25 hover:text-primary hover:bg-primary/10 transition-colors"
							title="Add to queue">
							<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
								<path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
							</svg>
						</button>

						<!-- Play -->
						<button
							onclick={() => playTrack(track)}
							class="w-7 h-7 flex items-center justify-center rounded-full flex-shrink-0
								text-base-content/20 hover:text-primary hover:bg-primary/10 transition-colors">
							<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
								<path d="M8 5v14l11-7z"/>
							</svg>
						</button>

					</div>
				{/each}
			</div>
		{/if}
	{/if}

</div>
