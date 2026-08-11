<script>
	// Extended CDC-600 remote controls — everything beyond play/pause/next/prev,
	// which the parent already handles with its own transport buttons.
	// Every command here is a zero-arg POST /api/cd/{cmd}; onCommand forwards
	// the string straight to the parent's sendCommand()-wrapping handler.
	let { state = 'stopped', busy = false, onCommand = null } = $props();

	function fire(cmd) {
		if (busy) return;
		onCommand?.(cmd);
	}

	let powerCmd = $derived(state === 'powered_off' ? 'power-on' : 'power-off');
</script>

<div class="flex flex-col items-center justify-center gap-5 transition-opacity {busy ? 'opacity-50 pointer-events-none' : ''}">

	<!-- Disc: prev / open-close / next -->
	<div class="flex items-center gap-1.5 bg-base-content/6 rounded-full p-1.5">
		<button
			onclick={() => fire('disc-prev')}
			class="w-11 h-11 flex items-center justify-center rounded-full
				text-base-content/60 hover:text-base-content/90 hover:bg-base-content/8 active:scale-90 transition-all"
			aria-label="Previous disc">
			<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
				<path d="M17.59 18 19 16.59 14.42 12 19 7.41 17.59 6l-6 6zM11.59 18 13 16.59 8.42 12 13 7.41 11.59 6l-6 6z"/>
			</svg>
		</button>
		<button
			onclick={() => fire('open-close')}
			class="w-11 h-11 flex items-center justify-center rounded-full
				text-base-content/60 hover:text-base-content/90 hover:bg-base-content/8 active:scale-90 transition-all"
			aria-label="Open or close tray">
			<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
				<path d="M5 17h14v2H5zm7-12L5.33 15h13.34z"/>
			</svg>
		</button>
		<button
			onclick={() => fire('disc-next')}
			class="w-11 h-11 flex items-center justify-center rounded-full
				text-base-content/60 hover:text-base-content/90 hover:bg-base-content/8 active:scale-90 transition-all"
			aria-label="Next disc">
			<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
				<path d="M6.41 6 5 7.41 9.58 12 5 16.59 6.41 18l6-6zM12.41 6 11 7.41 15.58 12 11 16.59 12.41 18l6-6z"/>
			</svg>
		</button>
	</div>

	<!-- Playback modifiers: search back / repeat / random / search forward -->
	<div class="flex items-center gap-1.5 bg-base-content/6 rounded-full p-1.5">
		<button
			onclick={() => fire('search-backward')}
			class="w-11 h-11 flex items-center justify-center rounded-full
				text-base-content/60 hover:text-base-content/90 hover:bg-base-content/8 active:scale-90 transition-all"
			aria-label="Search backward">
			<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
				<path d="M11 18V6l-8.5 6L11 18zm.5-6L20 6v12l-8.5-6z"/>
			</svg>
		</button>
		<button
			onclick={() => fire('repeat')}
			class="w-11 h-11 flex items-center justify-center rounded-full
				text-base-content/60 hover:text-base-content/90 hover:bg-base-content/8 active:scale-90 transition-all"
			aria-label="Repeat">
			<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
				<path d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z"/>
			</svg>
		</button>
		<button
			onclick={() => fire('random')}
			class="w-11 h-11 flex items-center justify-center rounded-full
				text-base-content/60 hover:text-base-content/90 hover:bg-base-content/8 active:scale-90 transition-all"
			aria-label="Random">
			<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
				<path d="M10.59 9.17 5.41 4 4 5.41l5.17 5.17 1.42-1.41zM14.5 4l2.04 2.04L4 18.59 5.41 20 17.96 7.46 20 9.5V4h-5.5zm.33 9.41-1.41 1.41 3.13 3.13L14.5 20H20v-5.5l-2.04 2.04-3.13-3.13z"/>
			</svg>
		</button>
		<button
			onclick={() => fire('search-forward')}
			class="w-11 h-11 flex items-center justify-center rounded-full
				text-base-content/60 hover:text-base-content/90 hover:bg-base-content/8 active:scale-90 transition-all"
			aria-label="Search forward">
			<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
				<path d="M4 18l8.5-6L4 6v12zm9-12v12l8.5-6z"/>
			</svg>
		</button>
	</div>

	<!-- Power -->
	<button
		onclick={() => fire(powerCmd)}
		class="w-11 h-11 flex items-center justify-center rounded-full
			text-base-content/60 hover:text-base-content/90 hover:bg-base-content/8 active:scale-90 transition-all"
		aria-label={state === 'powered_off' ? 'Power on' : 'Power off'}>
		<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
			<path d="M13 3h-2v10h2V3zm4.83 2.17-1.42 1.42A6.92 6.92 0 0 1 19 12c0 3.87-3.13 7-7 7s-7-3.13-7-7c0-2.24 1.06-4.24 2.71-5.5L6.29 5.08A8.936 8.936 0 0 0 3 12c0 4.97 4.03 9 9 9s9-4.03 9-9c0-2.85-1.33-5.39-3.17-6.83z"/>
		</svg>
	</button>

</div>
