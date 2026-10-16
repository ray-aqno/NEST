import { useEffect, useState } from "react";
import type { CarId, RaceState } from "./types";

// Foundation shell (T1): proves server -> SSE -> UI. The real pit board is T6.
export function App() {
  const [state, setState] = useState<RaceState | null>(null);
  const [online, setOnline] = useState(false);

  useEffect(() => {
    const source = new EventSource("/stream");
    source.onopen = () => setOnline(true);
    source.onerror = () => setOnline(false); // EventSource reconnects on its own
    source.onmessage = (msg) => setState(JSON.parse(msg.data) as RaceState);
    return () => source.close();
  }, []);

  return (
    <main>
      <header>
        <h1>NEST</h1>
        <span className={online ? "ok" : "bad"}>{online ? "server connected" : "server offline"}</span>
      </header>
      {state && (
        <>
          <p>
            race {state.race_id ?? "(none yet)"} · seq {state.last_seq}
          </p>
          <section className="cars">
            {(["A", "B"] as CarId[]).map((id) => (
              <article key={id}>
                <h2>
                  {id} · {state.config.cars[id].name}
                </h2>
                <dl>
                  <dt>laps</dt>
                  <dd>{state.cars[id].laps.length}</dd>
                  <dt>status</dt>
                  <dd>{state.cars[id].status}</dd>
                  <dt>driver</dt>
                  <dd>{state.cars[id].driver ?? "—"}</dd>
                </dl>
              </article>
            ))}
          </section>
        </>
      )}
    </main>
  );
}
