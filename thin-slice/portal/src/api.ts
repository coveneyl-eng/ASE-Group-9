// All calls go through the NGINX gateway, so the same paths work in Docker Compose and in Azure.
export interface Session {
  token: string;
  role: string;
  user: string;
}

export async function login(username: string, password: string): Promise<Session> {
  const r = await fetch("/api/approval/token", { method: "POST", body: new URLSearchParams({ username, password }) });
  if (!r.ok) throw new Error(r.status === 401 ? "Wrong username or password" : `Sign-in failed (${r.status})`);
  const body = (await r.json()) as { access_token: string; role: string };
  return { token: body.access_token, role: body.role, user: username };
}

export async function call<T>(session: Session, path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${session.token}`, ...init.headers },
  });
  if (!r.ok) {
    const detail = await r.json().then((b) => b.detail).catch(() => r.statusText);
    throw new Error(`${r.status}: ${detail}`);
  }
  return (await r.json()) as T;
}

/** Python sends ISO times with microseconds; trim to milliseconds so every browser parses them. */
export function parseTime(iso: string): number {
  return Date.parse(iso.replace(/(\.\d{3})\d+/, "$1"));
}
