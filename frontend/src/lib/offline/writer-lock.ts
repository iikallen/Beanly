export type WriterLease = { release: () => void };

export async function acquireWriterLock(onChange: (writer: boolean) => void): Promise<WriterLease> {
  if (navigator.locks) {
    let release = () => {};
    const held = new Promise<void>((resolve) => { release = resolve; });
    void navigator.locks.request("beanly-pos-writer", { ifAvailable: true }, async (lock) => {
      onChange(Boolean(lock));
      if (lock) await held;
    });
    return { release };
  }

  if (!("BroadcastChannel" in globalThis)) {
    onChange(false);
    return { release: () => undefined };
  }

  // ponytail: BroadcastChannel election is best-effort; remove when Web Locks is universal.
  const channel = new BroadcastChannel("beanly-pos-writer");
  const token = crypto.randomUUID();
  const contenders = new Map([[token, Date.now()]]);
  let writer = false;
  channel.onmessage = (event) => {
    if (event.data?.type === "PROBE") channel.postMessage({ type: "HEARTBEAT", token });
    if (event.data?.type === "HEARTBEAT") contenders.set(event.data.token, Date.now());
  };
  channel.postMessage({ type: "PROBE" });
  channel.postMessage({ type: "HEARTBEAT", token });
  await new Promise((resolve) => setTimeout(resolve, 180));
  const heartbeat = window.setInterval(() => {
    const now = Date.now();
    contenders.set(token, now);
    for (const [candidate, seenAt] of contenders) if (now - seenAt > 2500) contenders.delete(candidate);
    const next = [...contenders.keys()].sort()[0] === token;
    if (next !== writer) {
      writer = next;
      onChange(writer);
    }
    channel.postMessage({ type: "HEARTBEAT", token });
  }, 1000);
  writer = [...contenders.keys()].sort()[0] === token;
  onChange(writer);
  return {
    release: () => {
      window.clearInterval(heartbeat);
      channel.close();
    },
  };
}
