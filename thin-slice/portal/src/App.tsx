import { useEffect, useState } from "react";
import { login, type Session } from "./api";
import { FloodMap } from "./FloodMap";
import { HealthDashboard } from "./HealthDashboard";
import type { FloodImpact } from "./messages";
import { Operations } from "./Operations";
import { useLiveFeed } from "./useLiveFeed";

const isPublic = new URLSearchParams(location.search).has("public");
type Tab = "health" | "operations";

function PublicStatusMap() {
  const [impact, setImpact] = useState<FloodImpact>();
  useEffect(() => {
    const load = () =>
      fetch("/api/state").then((r) => r.json()).then((s) => setImpact(s["flood.impacts"]?.data as FloodImpact));
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);
  const unsafe = impact?.impacts.filter((a) => a.status === "unsafe").map((a) => a.name) ?? [];
  return (
    <main className="public">
      {/* Warning text first so it shows before map tiles on slow connections */}
      <h1>Dublin flood status</h1>
      <p className="warning">{unsafe.length ? `⚠ Avoid: ${unsafe.join(", ")}` : "No active flood warnings."}</p>
      <FloodMap impact={impact} />
    </main>
  );
}

function SignIn({ onSession }: { onSession: (s: Session) => void }) {
  const [error, setError] = useState("");
  return (
    <form
      className="signin card"
      onSubmit={async (e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        try {
          onSession(await login(String(f.get("u")), String(f.get("p"))));
        } catch (err) {
          setError(String(err));
        }
      }}
    >
      <h1>Dublin Smart City</h1>
      <p className="muted">Officials' coordination portal</p>
      <input name="u" placeholder="Username" defaultValue="dispatcher" autoComplete="username" />
      <input name="p" type="password" placeholder="Password" defaultValue="dispatch-demo" autoComplete="current-password" />
      <button>Sign in</button>
      {error && <p className="error">{error}</p>}
      <a href="?public">Public status map</a>
    </form>
  );
}

function Shell({ session, onSignOut }: { session: Session; onSignOut: () => void }) {
  const [tab, setTab] = useState<Tab>("health");
  const { messages, connection } = useLiveFeed(session.token);
  return (
    <div className="shell">
      <header className="topbar">
        <strong>Dublin Smart City</strong>
        <nav>
          <button className={tab === "health" ? "tab active" : "tab"} onClick={() => setTab("health")}>
            System health
          </button>
          <button className={tab === "operations" ? "tab active" : "tab"} onClick={() => setTab("operations")}>
            Operations
          </button>
        </nav>
        <span className={`conn conn-${connection}`}>{connection === "live" ? "Live" : connection}</span>
        <span className="muted">
          {session.user} · {session.role.replace("_", " ")}
        </span>
        <button className="link" onClick={onSignOut}>
          Sign out
        </button>
      </header>
      <main>
        {tab === "health" ? (
          <HealthDashboard session={session} messages={messages} />
        ) : (
          <Operations session={session} messages={messages} />
        )}
      </main>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<Session>();
  if (isPublic) return <PublicStatusMap />;
  return session ? <Shell session={session} onSignOut={() => setSession(undefined)} /> : <SignIn onSession={setSession} />;
}
