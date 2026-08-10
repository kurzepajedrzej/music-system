import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { connectWs } from './ws.js';

class FakeWebSocket {
	static instances = [];
	constructor(url) {
		this.url = url;
		this.closed = false;
		this.onmessage = null;
		this.onclose = null;
		FakeWebSocket.instances.push(this);
	}
	close() {
		this.closed = true;
	}
	triggerClose() {
		this.onclose?.();
	}
}

describe('connectWs', () => {
	beforeEach(() => {
		FakeWebSocket.instances = [];
		vi.stubGlobal('WebSocket', FakeWebSocket);
		vi.useFakeTimers();
	});
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.useRealTimers();
	});

	it('close() closes the current socket even after a reconnect', () => {
		const handle = connectWs(
			() => {},
			() => {},
			() => {}
		);
		const first = FakeWebSocket.instances[0];

		first.triggerClose();
		vi.advanceTimersByTime(3100);

		const second = FakeWebSocket.instances[1];
		expect(second).toBeDefined();
		expect(second).not.toBe(first);

		handle.close();
		expect(second.closed).toBe(true);
	});

	it('closes the old socket before creating a new one on reconnect', () => {
		connectWs(
			() => {},
			() => {},
			() => {}
		);
		const first = FakeWebSocket.instances[0];
		first.triggerClose();
		vi.advanceTimersByTime(3100);
		expect(first.closed).toBe(true);
	});
});
