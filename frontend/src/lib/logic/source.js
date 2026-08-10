let inFlight = false;

export async function switchSource({ target, apiSwitchSource }) {
	if (inFlight) {
		throw new Error('switch already in progress');
	}
	inFlight = true;
	try {
		await apiSwitchSource(target);
		return target;
	} finally {
		inFlight = false;
	}
}
