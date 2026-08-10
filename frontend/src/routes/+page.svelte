<script>
	import { browser } from '$app/environment';
	import { onMount, onDestroy } from 'svelte';
	import { fly } from 'svelte/transition';
	import { sendCommand } from '$lib/api/cdcontrol.js';
	import { playerCommand, seekTo, artworkUrl, removeQueueItem, playQueueItem, getState, switchSource } from '$lib/api/owntone.js';
	import { connectWs } from '$lib/api/ws.js';
	import { switchSource as switchSourceLogic } from '$lib/logic/source.js';
	import { computeSeekTarget } from '$lib/logic/seek.js';
	import Library      from '$lib/components/Library.svelte';
	import AirPlayZones from '$lib/components/AirPlayZones.svelte';
	import Queue        from '$lib/components/Queue.svelte';

	// ── Theme ──────────────────────────────────────────────────────────────
	let theme = $state(browser ? (localStorage.getItem('music-theme') || 'musiclight') : 'musiclight');
	$effect(() => { if (browser) document.documentElement.setAttribute('data-theme', theme); });
	function toggleTheme() {
		theme = theme === 'musiclight' ? 'musicdark' : 'musiclight';
		localStorage.setItem('music-theme', theme);
	}

	// ── UI state ───────────────────────────────────────────────────────────
	let source      = $state(browser ? (localStorage.getItem('music-source') || 'cd') : 'cd');
	let activePanel = $state(null);    // null | 'library' | 'airplay'
	$effect(() => { if (browser) localStorage.setItem('music-source', source); });

	let switching = $state(false);
	async function doSwitchSource(target) {
		// No-op if already on the target source — /api/source/cd is not
		// idempotent (it stops and restarts the pipe), so re-issuing it while
		// already on CD would audibly interrupt live playback.
		if (switching || target === source) return;
		switching = true;
		try {
			source = await switchSourceLogic({ current: source, target, apiSwitchSource: switchSource });
		} catch {
			// switch failed — leave `source` unchanged, matching pre-switch state
		} finally {
			switching = false;
		}
	}

	// ── Responsive layout ──────────────────────────────────────────────────
	let isDesktop = $state(false);
	$effect(() => {
		if (!browser) return;
		const mq = window.matchMedia('(min-width: 1024px)');
		isDesktop = mq.matches;
		const handler = (e) => { isDesktop = e.matches; };
		mq.addEventListener('change', handler);
		return () => mq.removeEventListener('change', handler);
	});

	// ── CD ─────────────────────────────────────────────────────────────────
	let cdStatus = $state({
		state: 'stopped', disc_present: false,
		track: 0, total_tracks: 0,
		elapsed_seconds: 0, track_duration_seconds: 0
	});

	function cdFmt(s) {
		const m = Math.floor(s / 60);
		return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
	}

	// ── Library / owntone ──────────────────────────────────────────────────
	let player       = $state(null);
	let currentTrack = $state(null);
	let queueItems   = $state([]);
	let libBusy = $state(false);
	let desktopRightTab = $state('airplay');
	let ws;

	function libFmt(ms) {
		if (ms == null) return '--:--';
		const s = Math.floor(ms / 1000);
		return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
	}

	// ── Unified controls ───────────────────────────────────────────────────
	let playing = $derived(
		source === 'cd' ? cdStatus.state === 'playing' : player?.state === 'play'
	);

	let cdBusy = $state(false);

	async function togglePlay() {
		if (source === 'cd') {
			if (cdBusy) return;
			cdBusy = true;
			try {
				await sendCommand(cdStatus.state === 'playing' ? 'pause' : 'play');
			} finally {
				cdBusy = false;
			}
		} else {
			if (libBusy) return;
			libBusy = true;
			const willPlay = player?.state !== 'play';
			player = { ...(player ?? {}), state: willPlay ? 'play' : 'pause' };
			try {
				await playerCommand(willPlay ? 'play' : 'pause');
			} finally {
				libBusy = false;
			}
		}
	}
	async function skipNext() {
		if (source === 'cd') {
			if (cdBusy) return;
			cdBusy = true;
			try {
				await sendCommand('next');
			} finally {
				cdBusy = false;
			}
		} else {
			player     = { ...(player ?? {}), state: 'play' };
			anchorPos  = 0;
			anchorTime = Date.now();
			await playerCommand('next');
		}
	}
	async function skipPrev() {
		if (source === 'cd') {
			if (cdBusy) return;
			cdBusy = true;
			try {
				await sendCommand('prev');
			} finally {
				cdBusy = false;
			}
		} else {
			player     = { ...(player ?? {}), state: 'play' };
			anchorPos  = 0;
			anchorTime = Date.now();
			await playerCommand('previous');
		}
	}

	// ── Progress ────────────────────────────────────────────────────────────
	let progressEl;
	let seeking = false;
	let timeElapsed = $state('--:--');
	let timeTotal   = $state('--:--');

	// Anchor: last position reported by backend + when we received it
	let anchorPos  = $state(0);
	let anchorTime = $state(0);

	// CD: reactive — cdStatus is kept live by the unified WebSocket
	$effect(() => {
		if (source !== 'cd') return;
		const dur = cdStatus.track_duration_seconds;
		const pct = dur > 0 ? Math.min(100, (cdStatus.elapsed_seconds / dur) * 100) : 0;
		timeElapsed = cdFmt(cdStatus.elapsed_seconds);
		timeTotal   = cdFmt(dur);
		if (progressEl) {
			progressEl.value = pct;
			progressEl.style.setProperty('--progress', pct + '%');
		}
	});

	// Library: RAF loop that interpolates position between 1s server ticks
	$effect(() => {
		if (source !== 'library') return;
		const _anchor    = anchorPos;
		const _startedAt = anchorTime;
		const _len       = player?.item_length_ms ?? 0;
		const _isPlaying = player?.state === 'play';

		timeTotal = _len > 0 ? libFmt(_len) : '--:--';

		if (!_len) return;

		let raf;
		function frame() {
			if (!seeking) {
				const elapsed = _isPlaying ? Math.max(0, Date.now() - _startedAt) : 0;
				const pos = Math.min(_anchor + elapsed, _len);
				const pct = _len > 0 ? (pos / _len) * 100 : 0;
				timeElapsed = libFmt(pos);
				if (progressEl) {
					progressEl.value = pct;
					progressEl.style.setProperty('--progress', pct + '%');
				}
			}
			raf = requestAnimationFrame(frame);
		}
		raf = requestAnimationFrame(frame);
		return () => cancelAnimationFrame(raf);
	});

	// Seek — pointerup is reliable on both desktop and mobile
	function onProgressInput(e) {
		seeking = true;
		const pct = +e.target.value;
		e.target.style.setProperty('--progress', pct + '%');
	}
	async function onProgressPointerUp(e) {
		if (!seeking) return;
		if (!player?.item_length_ms) { seeking = false; return; }
		const { positionMs, resumeState } = computeSeekTarget({
			player,
			valuePercent: +e.target.value
		});
		anchorPos  = positionMs;
		anchorTime = Date.now();
		player     = { ...player, state: resumeState };
		seeking    = false;
		await seekTo(positionMs);
	}

	// ── Track info ─────────────────────────────────────────────────────────
	let trackTitle = $derived(
		source === 'cd'
			? (cdStatus.disc_present ? `Track ${String(cdStatus.track).padStart(2, '0')}` : 'No Disc')
			: (currentTrack?.title ?? 'Not Playing')
	);
	let trackSub = $derived(
		source === 'cd'
			? (cdStatus.disc_present ? `${cdStatus.total_tracks} tracks` : '')
			: (currentTrack?.artist ?? '')
	);

	// ── Library panel callback ─────────────────────────────────────────────
	function onLibraryPlay(track = null) {
		source      = 'library';
		activePanel = null;

		// Optimistic state so button flips immediately
		if (track) {
			currentTrack = track;
			player = { ...(player ?? {}), state: 'play', item_progress_ms: 0, item_length_ms: track.length_ms ?? 0 };
			anchorPos  = 0;
			anchorTime = Date.now();
			if (progressEl) { progressEl.value = 0; progressEl.style.setProperty('--progress', '0%'); }
			timeElapsed = '0:00';
			timeTotal   = libFmt(track.length_ms);
		} else {
			player = { ...(player ?? {}), state: 'play' };
		}
		// Backend handles waiting — WebSocket will deliver confirmed state
	}

	// ── Queue actions ──────────────────────────────────────────────────────
	async function onQueueJump(item) {
		source     = 'library';
		player     = { ...(player ?? {}), state: 'play' };
		anchorPos  = 0;
		anchorTime = Date.now();
		await playQueueItem(item.id);
		// Backend waits for confirmation + handles cleanup — WebSocket delivers update
	}

	async function onQueueRemove(item) {
		await removeQueueItem(item.id);
		// WebSocket will deliver updated queue
	}

	// ── WebSocket state handler ────────────────────────────────────────────
	function onWsState(msg) {
		if (msg.player) {
			player       = msg.player;
			anchorPos    = msg.player.item_progress_ms ?? 0;
			anchorTime   = Date.now();
		}
		if (msg.queue) {
			queueItems   = msg.queue;
		}
		if (msg.currentTrack !== undefined) {
			currentTrack = msg.currentTrack;
		}
		if (msg.cd) {
			cdStatus     = msg.cd;
		}
	}

	function onWsTick(msg) {
		anchorPos  = msg.position_ms;
		anchorTime = Date.now();
	}

	// ── Lifecycle ──────────────────────────────────────────────────────────
	onMount(async () => {
		// Single REST call for instant hydration
		try {
			const state = await getState();
			if (state.player)       player       = state.player;
			if (state.queue)        queueItems   = state.queue;
			if (state.currentTrack) currentTrack = state.currentTrack;
			if (state.cd)           cdStatus     = state.cd;
			if (player?.item_id) source = 'library';
			anchorPos  = state.player?.item_progress_ms ?? 0;
			anchorTime = Date.now();
		} catch {}

		// Single WebSocket for all real-time updates
		ws = connectWs(onWsState, onWsTick, (msg) => { cdStatus = msg.cd; });
	});
	onDestroy(() => {
		ws?.close();
	});

	function onImgError(e) {
		e.target.style.display = 'none';
		e.target.nextElementSibling?.classList.remove('hidden');
	}
</script>

{#if isDesktop}
<!-- ═══ DESKTOP LAYOUT ═══════════════════════════════════════════════════ -->
<div class="h-screen flex flex-col bg-base-100" style="z-index:1">

	<!-- Top nav -->
	<div class="nav-glass flex-shrink-0">
		<header class="flex items-center justify-between px-8 py-3">
			<h1 class="text-xl font-bold tracking-tight text-base-content">Music Hub</h1>
			<div class="flex items-center gap-3">
				<button
					onclick={() => doSwitchSource(source === 'cd' ? 'library' : 'cd')}
					class="text-[13px] font-semibold px-4 py-1.5 rounded-full transition-all duration-200
						{source === 'cd'
							? 'bg-primary/15 text-primary'
							: 'bg-base-content/8 text-base-content/50 hover:text-base-content/70'}"
				>
					{source === 'cd' ? 'CD' : 'Library'}
				</button>
				<button
					onclick={toggleTheme}
					class="w-9 h-9 flex items-center justify-center rounded-full
						text-base-content/40 hover:text-base-content/70 hover:bg-base-content/8 transition-all"
					aria-label="Toggle theme"
				>
					{#if theme === 'musicdark'}
						<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
							<path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1zM11 2v2c0 .55.45 1 1 1s1-.45 1-1V2c0-.55-.45-1-1-1s-1 .45-1 1zm0 18v2c0 .55.45 1 1 1s1-.45 1-1v-2c0-.55-.45-1-1-1s-1 .45-1 1zM5.99 4.58a.996.996 0 0 0-1.41 0 .996.996 0 0 0 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41L5.99 4.58zm12.37 12.37a.996.996 0 0 0-1.41 0 .996.996 0 0 0 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0a.996.996 0 0 0 0-1.41l-1.06-1.06zm1.06-12.37-1.06 1.06a.996.996 0 0 0 0 1.41c.39.39 1.03.39 1.41 0l1.06-1.06a.996.996 0 0 0 0-1.41.996.996 0 0 0-1.41 0zM7.05 18.36l-1.06 1.06a.996.996 0 0 0 0 1.41c.39.39 1.03.39 1.41 0l1.06-1.06a.996.996 0 0 0 0-1.41.996.996 0 0 0-1.41 0z"/>
						</svg>
					{:else}
						<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
							<path d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36a5.389 5.389 0 0 1-4.4 2.26 5.403 5.403 0 0 1-3.14-9.8c-.44-.06-.9-.1-1.36-.1z"/>
						</svg>
					{/if}
				</button>
			</div>
		</header>
	</div>

	<!-- 3-column body -->
	<div class="flex-1 flex min-h-0">

		<!-- Left sidebar: Library -->
		<aside class="w-80 flex-shrink-0 border-r border-base-content/8 overflow-y-auto">
			<Library onPlay={onLibraryPlay} onQueue={() => {}} />
		</aside>

		<!-- Center: Now Playing -->
		<main class="flex-1 min-w-0 flex flex-col items-center justify-center px-12 py-8 gap-6 overflow-y-auto">

			<!-- Artwork -->
			<div class="w-80 h-80 flex-shrink-0">
				{#if source === 'cd'}
					<div class="disc-wrap {cdStatus.state === 'playing' ? 'playing' : ''} w-full" style="aspect-ratio:1">
						<div class="disc w-full h-full
							{cdStatus.state === 'playing' ? 'disc-playing' : cdStatus.state === 'paused' ? 'disc-paused' : ''}">
						</div>
					</div>
				{:else}
					<div class="w-full h-full rounded-[2rem] overflow-hidden shadow-2xl bg-base-300 flex items-center justify-center">
						{#if currentTrack?.album_id}
							<img src={artworkUrl(currentTrack.album_id, 600)} alt="" class="w-full h-full object-cover" onerror={onImgError} />
							<span class="hidden">
								<svg class="w-24 h-24 text-base-content/20" viewBox="0 0 24 24" fill="currentColor">
									<path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
								</svg>
							</span>
						{:else}
							<svg class="w-24 h-24 text-base-content/20" viewBox="0 0 24 24" fill="currentColor">
								<path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
							</svg>
						{/if}
					</div>
				{/if}
			</div>

			<!-- Track info -->
			<div class="text-center max-w-md w-full">
				<p class="text-2xl font-bold text-base-content truncate leading-tight">{trackTitle}</p>
				<p class="text-base text-base-content/50 truncate mt-1">{trackSub}</p>
				{#if source === 'cd' && cdStatus.disc_present && cdStatus.total_tracks > 0 && cdStatus.total_tracks <= 20}
					<div class="flex justify-center gap-1.5 mt-3">
						{#each Array(cdStatus.total_tracks) as _, i}
							<div class="w-2 h-2 rounded-full transition-all duration-300
								{i + 1 === cdStatus.track ? 'bg-primary scale-125' : i + 1 < cdStatus.track ? 'bg-base-content/25' : 'bg-base-content/12'}">
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Progress bar -->
			<div class="w-full max-w-md">
				<input
					bind:this={progressEl}
					type="range"
					class="progress-bar"
					min="0" max="100"
					readonly={source === 'cd'}
					oninput={player ? onProgressInput : null}
					onpointerup={player ? onProgressPointerUp : null}
					onchange={player ? onProgressPointerUp : null}
				/>
				<div class="flex justify-between mt-1.5 text-[12px] tabular-nums text-base-content/35">
					<span>{timeElapsed}</span>
					<span>{timeTotal}</span>
				</div>
			</div>

			<!-- Controls -->
			<div class="flex items-center gap-10">
				<button
					onclick={skipPrev}
					class="w-14 h-14 flex items-center justify-center rounded-full
						text-base-content/60 hover:text-base-content/90 hover:bg-base-content/8 active:scale-90 transition-all"
					aria-label="Previous">
					<svg class="w-9 h-9" viewBox="0 0 24 24" fill="currentColor">
						<path d="M6 6h2v12H6zm3.5 6 8.5 6V6z"/>
					</svg>
				</button>

				<button
					onclick={togglePlay}
					disabled={(source === 'library' && libBusy) || (source === 'cd' && cdBusy)}
					class="w-20 h-20 flex items-center justify-center rounded-full
						btn-play-glass active:scale-90 transition-all
						{(source === 'library' && libBusy) || (source === 'cd' && cdBusy) ? 'opacity-60' : ''}"
					aria-label={playing ? 'Pause' : 'Play'}>
					{#if playing}
						<svg class="w-8 h-8" viewBox="0 0 24 24" fill="currentColor">
							<path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
						</svg>
					{:else}
						<svg class="w-8 h-8" viewBox="0 0 24 24" fill="currentColor">
							<path d="M8 4v16l12-8z"/>
						</svg>
					{/if}
				</button>

				<button
					onclick={skipNext}
					class="w-14 h-14 flex items-center justify-center rounded-full
						text-base-content/60 hover:text-base-content/90 hover:bg-base-content/8 active:scale-90 transition-all"
					aria-label="Next">
					<svg class="w-9 h-9" viewBox="0 0 24 24" fill="currentColor">
						<path d="M6 18l8.5-6L6 6v12zM16 6h2v12h-2z"/>
					</svg>
				</button>
			</div>

		</main>

		<!-- Right sidebar: Queue / AirPlay (tabbed) -->
		<aside class="w-72 flex-shrink-0 border-l border-base-content/8 flex flex-col">
			<!-- Tabs -->
			<div class="flex border-b border-base-content/8 flex-shrink-0">
				<button
					onclick={() => { desktopRightTab = 'queue'; }}
					class="flex-1 py-3 text-[12px] font-semibold tracking-wide transition-colors
						{desktopRightTab === 'queue'
							? 'text-primary border-b-2 border-primary -mb-px'
							: 'text-base-content/40 hover:text-base-content/70'}">
					Queue
				</button>
				<button
					onclick={() => desktopRightTab = 'airplay'}
					class="flex-1 py-3 text-[12px] font-semibold tracking-wide transition-colors
						{desktopRightTab === 'airplay'
							? 'text-primary border-b-2 border-primary -mb-px'
							: 'text-base-content/40 hover:text-base-content/70'}">
					AirPlay
				</button>
			</div>
			<!-- Content -->
			<div class="flex-1 overflow-y-auto">
				{#if desktopRightTab === 'queue'}
					<Queue items={queueItems} currentItemId={player?.item_id ?? null} onJump={onQueueJump} onRemove={onQueueRemove} />
				{:else}
					<AirPlayZones />
				{/if}
			</div>
		</aside>

	</div>

</div>

{:else}
<!-- ═══ MOBILE LAYOUT ════════════════════════════════════════════════════ -->
<div class="relative flex flex-col h-[100dvh] overflow-hidden max-w-md mx-auto bg-base-100" style="z-index:1">

	<!-- Minimal nav bar -->
	<div class="nav-glass safe-top flex-shrink-0">
		<header class="flex items-center justify-between px-6 pt-4 pb-3">
			<h1 class="text-xl font-bold tracking-tight text-base-content">Music Hub</h1>
			<div class="flex items-center gap-2">
				<!-- Source toggle (testability) -->
				<button
					onclick={() => doSwitchSource(source === 'cd' ? 'library' : 'cd')}
					class="text-[12px] font-semibold px-3 py-1.5 rounded-full transition-all duration-200
						{source === 'cd'
							? 'bg-primary/15 text-primary'
							: 'bg-base-content/8 text-base-content/50 hover:text-base-content/70'}"
				>
					{source === 'cd' ? 'CD' : 'Library'}
				</button>
				<!-- Theme -->
				<button
					onclick={toggleTheme}
					class="w-8 h-8 flex items-center justify-center rounded-full
						text-base-content/40 hover:text-base-content/70 hover:bg-base-content/8 transition-all"
					aria-label="Toggle theme"
				>
					{#if theme === 'musicdark'}
						<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
							<path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1zM11 2v2c0 .55.45 1 1 1s1-.45 1-1V2c0-.55-.45-1-1-1s-1 .45-1 1zm0 18v2c0 .55.45 1 1 1s1-.45 1-1v-2c0-.55-.45-1-1-1s-1 .45-1 1zM5.99 4.58a.996.996 0 0 0-1.41 0 .996.996 0 0 0 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41L5.99 4.58zm12.37 12.37a.996.996 0 0 0-1.41 0 .996.996 0 0 0 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0a.996.996 0 0 0 0-1.41l-1.06-1.06zm1.06-12.37-1.06 1.06a.996.996 0 0 0 0 1.41c.39.39 1.03.39 1.41 0l1.06-1.06a.996.996 0 0 0 0-1.41.996.996 0 0 0-1.41 0zM7.05 18.36l-1.06 1.06a.996.996 0 0 0 0 1.41c.39.39 1.03.39 1.41 0l1.06-1.06a.996.996 0 0 0 0-1.41.996.996 0 0 0-1.41 0z"/>
						</svg>
					{:else}
						<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
							<path d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36a5.389 5.389 0 0 1-4.4 2.26 5.403 5.403 0 0 1-3.14-9.8c-.44-.06-.9-.1-1.36-.1z"/>
						</svg>
					{/if}
				</button>
			</div>
		</header>
	</div>

	<!-- Now Playing layout -->
	<div class="flex-1 min-h-0 flex flex-col px-6 pt-3 pb-2 gap-3">

		<!-- Artwork — fills available vertical space -->
		<div class="flex-1 min-h-0 flex items-center justify-center">
			{#if source === 'cd'}
				<!-- CD disc: circle centred in available space -->
				<div
					class="disc-wrap {cdStatus.state === 'playing' ? 'playing' : ''} w-full"
					style="aspect-ratio: 1 / 1; max-height: 100%"
				>
					<div class="disc w-full h-full
						{cdStatus.state === 'playing' ? 'disc-playing' : cdStatus.state === 'paused' ? 'disc-paused' : ''}">
					</div>
				</div>
			{:else}
				<!-- Album art square with rounded corners -->
				<div class="w-full aspect-square max-h-full rounded-[2rem] overflow-hidden shadow-2xl
					bg-base-300 flex items-center justify-center">
					{#if currentTrack?.album_id}
						<img
							src={artworkUrl(currentTrack.album_id, 600)}
							alt=""
							class="w-full h-full object-cover"
							onerror={onImgError}
						/>
						<span class="hidden">
							<svg class="w-24 h-24 text-base-content/20" viewBox="0 0 24 24" fill="currentColor">
								<path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
							</svg>
						</span>
					{:else}
						<svg class="w-24 h-24 text-base-content/20" viewBox="0 0 24 24" fill="currentColor">
							<path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
						</svg>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Track info -->
		<div class="flex items-center justify-between">
			<div class="min-w-0">
				<p class="text-[18px] font-bold text-base-content truncate leading-tight">{trackTitle}</p>
				<p class="text-[14px] text-base-content/50 truncate mt-0.5">{trackSub}</p>
			</div>
			{#if source === 'cd' && cdStatus.disc_present}
				<!-- Track dots -->
				{#if cdStatus.total_tracks > 0 && cdStatus.total_tracks <= 20}
					<div class="flex flex-wrap justify-end gap-1 max-w-[80px] flex-shrink-0 ml-3">
						{#each Array(cdStatus.total_tracks) as _, i}
							<div class="w-1.5 h-1.5 rounded-full transition-all duration-300
								{i + 1 === cdStatus.track ? 'bg-primary scale-125' : i + 1 < cdStatus.track ? 'bg-base-content/25' : 'bg-base-content/12'}">
							</div>
						{/each}
					</div>
				{/if}
			{/if}
		</div>

		<!-- Progress bar -->
		<div>
			<input
				bind:this={progressEl}
				type="range"
				class="progress-bar"
				min="0" max="100"
				readonly={source === 'cd'}
				oninput={player ? onProgressInput : null}
				onpointerup={player ? onProgressPointerUp : null}
				onchange={player ? onProgressPointerUp : null}
			/>
			<div class="flex justify-between mt-1.5 text-[11px] tabular-nums text-base-content/35">
				<span>{timeElapsed}</span>
				<span>{timeTotal}</span>
			</div>
		</div>

		<!-- Controls -->
		<div class="flex items-center justify-between px-2">
			<button
				onclick={skipPrev}
				class="w-14 h-14 flex items-center justify-center rounded-full
					text-base-content/60 hover:text-base-content/90 active:scale-90 transition-all"
				aria-label="Previous">
				<svg class="w-9 h-9" viewBox="0 0 24 24" fill="currentColor">
					<path d="M6 6h2v12H6zm3.5 6 8.5 6V6z"/>
				</svg>
			</button>

			<button
				onclick={togglePlay}
				disabled={(source === 'library' && libBusy) || (source === 'cd' && cdBusy)}
				class="w-20 h-20 flex items-center justify-center rounded-full
					btn-play-glass active:scale-90 transition-all
					{(source === 'library' && libBusy) || (source === 'cd' && cdBusy) ? 'opacity-60' : ''}"
				aria-label={playing ? 'Pause' : 'Play'}>
				{#if playing}
					<svg class="w-8 h-8" viewBox="0 0 24 24" fill="currentColor">
						<path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
					</svg>
				{:else}
					<svg class="w-8 h-8" viewBox="0 0 24 24" fill="currentColor">
						<path d="M8 4v16l12-8z"/>
					</svg>
				{/if}
			</button>

			<button
				onclick={skipNext}
				class="w-14 h-14 flex items-center justify-center rounded-full
					text-base-content/60 hover:text-base-content/90 active:scale-90 transition-all"
				aria-label="Next">
				<svg class="w-9 h-9" viewBox="0 0 24 24" fill="currentColor">
					<path d="M6 18l8.5-6L6 6v12zM16 6h2v12h-2z"/>
				</svg>
			</button>
		</div>

		<!-- Bottom action bar -->
		<div class="flex items-center justify-around safe-bottom pb-1 flex-shrink-0">

			<!-- CD source -->
			<button
				onclick={() => { doSwitchSource('cd'); activePanel = null; }}
				class="flex flex-col items-center gap-1 w-14 transition-colors
					{source === 'cd' && !activePanel ? 'text-primary' : 'text-base-content/35 hover:text-base-content/60'}"
				aria-label="CD Player">
				<svg class="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
					<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 14c-2.21 0-4-1.79-4-4s1.79-4 4-4 4 1.79 4 4-1.79 4-4 4zm0-6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/>
				</svg>
				<span class="text-[10px] font-medium">CD</span>
			</button>

			<!-- Library -->
			<button
				onclick={() => activePanel = activePanel === 'library' ? null : 'library'}
				class="flex flex-col items-center gap-1 w-14 transition-colors
					{activePanel === 'library' ? 'text-primary' : 'text-base-content/35 hover:text-base-content/60'}"
				aria-label="Library">
				<svg class="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
					<path d="M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-1 9H9V9h10v2zm-4 4H9v-2h6v2zm4-8H9V5h10v2z"/>
				</svg>
				<span class="text-[10px] font-medium">Library</span>
			</button>

			<!-- Queue -->
			<button
				onclick={() => { activePanel = activePanel === 'queue' ? null : 'queue'; }}
				class="flex flex-col items-center gap-1 w-14 transition-colors
					{activePanel === 'queue' ? 'text-primary' : 'text-base-content/35 hover:text-base-content/60'}"
				aria-label="Queue">
				<svg class="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
					<path d="M15 6H3v2h12V6zm0 4H3v2h12v-2zM3 16h8v-2H3v2zM17 6v8.18c-.31-.11-.65-.18-1-.18-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3V8h3V6h-5z"/>
				</svg>
				<span class="text-[10px] font-medium">Queue</span>
			</button>

			<!-- AirPlay -->
			<button
				onclick={() => activePanel = activePanel === 'airplay' ? null : 'airplay'}
				class="flex flex-col items-center gap-1 w-14 transition-colors
					{activePanel === 'airplay' ? 'text-primary' : 'text-base-content/35 hover:text-base-content/60'}"
				aria-label="AirPlay">
				<svg class="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
					<path d="M6 22h12l-6-6-6 6zM21 3H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h4v-2H3V5h18v12h-4v2h4c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z"/>
				</svg>
				<span class="text-[10px] font-medium">AirPlay</span>
			</button>

		</div>
	</div>

	<!-- Slide-up panel backdrop -->
	{#if activePanel}
		<div
			class="fixed inset-0 z-40 bg-black/25"
			onclick={() => activePanel = null}
			transition:fly={{ duration: 200, y: 0, opacity: 1 }}
		></div>

		<!-- Panel -->
		<div
			class="fixed inset-x-0 bottom-0 z-50 glass rounded-t-3xl safe-bottom overflow-hidden"
			style="max-width: 28rem; margin: 0 auto; max-height: 72vh"
			transition:fly={{ y: 400, duration: 320 }}
		>
			<!-- Drag handle -->
			<div class="flex justify-center pt-3 pb-1 flex-shrink-0">
				<div class="w-10 h-1 rounded-full bg-base-content/20"></div>
			</div>

			<!-- Panel title -->
			<div class="px-5 pb-2 flex items-center justify-between flex-shrink-0">
				<p class="text-[13px] font-semibold tracking-[0.15em] uppercase text-base-content/40">
					{activePanel === 'library' ? 'Library' : activePanel === 'queue' ? 'Queue' : 'AirPlay'}
				</p>
				<button
					onclick={() => activePanel = null}
					class="text-[13px] font-semibold text-primary hover:text-primary/70 transition-colors">
					Done
				</button>
			</div>

			<!-- Scrollable content -->
			<div class="overflow-y-auto" style="max-height: calc(72vh - 4rem)">
				{#if activePanel === 'library'}
					<Library onPlay={onLibraryPlay} onQueue={() => {}} />
				{:else if activePanel === 'queue'}
					<Queue items={queueItems} currentItemId={player?.item_id ?? null} onJump={onQueueJump} onRemove={onQueueRemove} />
				{:else}
					<AirPlayZones />
				{/if}
			</div>
		</div>
	{/if}

</div>
{/if}
