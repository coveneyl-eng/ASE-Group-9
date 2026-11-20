import { useEffect, useRef, useState } from "react";
import type { BusMessage } from "./messages";

export type Connection = "connecting" | "live" | "reconnecting";

/** One WebSocket to the hub for the whole app; reconnects with back-off and keeps the last 200 messages. */
export function useLiveFeed(token: string) {
  const [messages, setMessages] = useState<BusMessage[]>([]);
  const [connection, setConnection] = useState<Connection>("connecting");
  const retry = useRef(0);

  useEffect(() => {
    let ws: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    const open = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`);
      ws.onopen = () => {
        retry.current = 0;
        setConnection("live");
      };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data) as Omit<BusMessage, "receivedAt">;
        if (msg.topic === "hello") return;
        setMessages((m) => [{ ...msg, receivedAt: Date.now() }, ...m].slice(0, 200));
      };
      ws.onclose = () => {
        if (closed) return;
        setConnection("reconnecting");
        timer = setTimeout(open, Math.min(10000, 1000 * 2 ** retry.current++));
      };
    };
    open();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, [token]);

  return { messages, connection };
}
