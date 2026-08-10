<script>
	import { onMount } from 'svelte';
	import { getOutputs, setOutput } from '$lib/api/owntone.js';

	let outputs = $state([]);
	let loading = $state(true);
	let error   = $state(null);

	async function load() {
		try {
			outputs = await getOutputs();
			error = null;
		} catch {
			error = 'Cannot reach owntone';
		} finally {
			loading = false;
		}
	}

	async function toggle(output) {
		output.selected = !output.selected;
		await setOutput(output.id, { enabled: output.selected });
		await load();
	}

	async function onVolume(output, value) {
		output.volume = value;
		await setOutput(output.id, { volume: value });
	}

	onMount(load);
</script>

<div class="flex flex-col gap-3 px-4 py-4">

	<p class="text-[11px] font-semibold tracking-[0.2em] uppercase text-base-content/35 px-1 mb-1">
		AirPlay Zones
	</p>

	{#if loading}
		<div class="flex justify-center py-16">
			<div class="w-6 h-6 rounded-full border-2 border-primary/30 border-t-primary animate-spin"></div>
		</div>

	{:else if error}
		<div class="bg-base-200 rounded-2xl p-4 flex items-center gap-3 shadow-sm">
			<div class="w-2 h-2 rounded-full bg-error flex-shrink-0"></div>
			<span class="text-sm text-base-content/50">{error}</span>
			<button onclick={load} class="ml-auto text-xs text-primary font-medium hover:text-primary/70 transition-colors">Retry</button>
		</div>

	{:else if outputs.length === 0}
		<p class="text-center text-base-content/25 py-16 text-sm">No outputs found</p>

	{:else}
		<div class="bg-base-200 rounded-2xl overflow-hidden shadow-sm">
			{#each outputs as output, i (output.id)}
				<div class="{i < outputs.length - 1 ? 'border-b border-base-content/6' : ''}
					{output.selected ? '' : 'opacity-50'}">

					<div class="flex items-center gap-3 px-4 py-3.5">
						<!-- Icon -->
						<div class="w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0
							{output.selected ? 'bg-primary/12 text-primary' : 'bg-base-content/6 text-base-content/30'}">
							{#if output.type === 'AirPlay 2' || output.type === 'AirPlay 1'}
								<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
									<path d="M6 22h12l-6-6-6 6zM21 3H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h4v-2H3V5h18v12h-4v2h4c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z"/>
								</svg>
							{:else if output.type === 'Chromecast'}
								<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
									<path d="M1 18v3h3c0-1.66-1.34-3-3-3zm0-4v2c2.76 0 5 2.24 5 5h2c0-3.87-3.13-7-7-7zm18-7H5c-1.1 0-2 .9-2 2v3h2v-3h14v10h-5v2h5c1.1 0 2-.9 2-2V9c0-1.1-.9-2-2-2zm-18 3v2c4.97 0 9 4.03 9 9h2c0-6.08-4.93-11-11-11z"/>
								</svg>
							{:else}
								<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
									<path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/>
								</svg>
							{/if}
						</div>

						<!-- Name + type -->
						<div class="flex-1 min-w-0">
							<p class="text-sm font-medium text-base-content truncate">{output.name}</p>
							<p class="text-[11px] text-base-content/35">{output.type}</p>
						</div>

						<!-- Toggle -->
						<button
							onclick={() => toggle(output)}
							class="relative w-12 h-7 rounded-full flex-shrink-0 transition-all duration-200
								{output.selected ? 'bg-primary' : 'bg-base-content/15'}"
							aria-label="Toggle {output.name}">
							<span class="absolute top-1 h-5 w-5 rounded-full bg-white shadow-sm transition-all duration-200
								{output.selected ? 'left-[26px]' : 'left-1'}"></span>
						</button>
					</div>

					<!-- Volume -->
					{#if output.selected}
						<div class="flex items-center gap-3 px-4 pb-4">
							<svg class="w-3.5 h-3.5 text-base-content/30 flex-shrink-0" viewBox="0 0 24 24" fill="currentColor">
								<path d="M7 9v6h4l5 5V4l-5 5H7z"/>
							</svg>
							<input
								type="range"
								class="vol-bar flex-1"
								min="0" max="100"
								value={output.volume ?? 50}
								style="--vol: {output.volume ?? 50}%"
								oninput={(e) => {
									output.volume = +e.target.value;
									e.target.style.setProperty('--vol', output.volume + '%');
								}}
								onchange={(e) => onVolume(output, +e.target.value)}
							/>
							<svg class="w-4 h-4 text-base-content/30 flex-shrink-0" viewBox="0 0 24 24" fill="currentColor">
								<path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
							</svg>
							<span class="text-xs text-base-content/35 w-7 text-right tabular-nums">{output.volume ?? 50}</span>
						</div>
					{/if}

				</div>
			{/each}
		</div>
	{/if}

	<button onclick={load}
		class="flex items-center justify-center gap-1.5 text-[12px] text-base-content/30
			hover:text-base-content/50 transition-colors mt-1 py-2">
		<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
			<path d="M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
		</svg>
		Refresh
	</button>

</div>
