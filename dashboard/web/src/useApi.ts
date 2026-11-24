import { useEffect, useRef, useState } from "react";
import type { LiveMessage } from "./types";

/** GET a JSON endpoint now and every `everyMs`; keeps the last good value and the last error. */
export function usePoll<T>(path: string, everyMs: number) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await fetch(path);
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `${r.status} ${r.statusText}`);
        const body = (await r.json()) as T;
        if (alive) {
          setData(body);
          setError("");
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    };
    load();
    const id = setInterval(load, everyMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [path, everyMs]);
  return { data, error };
}

export type FeedState = "connecting" | "live" | "reconnecting";

/** The live Kafka feed from /api/live; reconnects with back-off and keeps the newest 50 messages. */
export function useLiveFeed() {
  const [messages, setMessages] = useState<LiveMessage[]>([]);
  const [state, setState] = useState<FeedState>("connecting");
  const retry = useRef(0);
  useEffect(() => {
    let ws: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    const open = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/live`);
      ws.onopen = () => {
        retry.current = 0;
        setState("live");
      };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data) as LiveMessage;
        setMessages((m) => [msg, ...m.filter((x) => x.offset !== msg.offset || x.partition !== msg.partition)].slice(0, 50));
      };
      ws.onclose = () => {
        if (closed) return;
        setState("reconnecting");
        timer = setTimeout(open, Math.min(10000, 1000 * 2 ** retry.current++));
      };
    };
    open();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, []);
  return { messages, state };
}

/** Python sends ISO times with microseconds; trim to milliseconds so every browser parses them. */
export function parseTime(iso: string): number {
  return Date.parse(iso.replace(/(\.\d{3})\d+/, "$1"));
}

export function clock(iso: string): string {
  return new Date(parseTime(iso)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
