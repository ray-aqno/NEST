// Mirrors server/engine/state.py reduce() output plus `now` from GET /state.
export type CarId = "A" | "B";

export interface CarState {
  laps: string[];
  driver: string | null;
  status: "track" | "pit" | "paddock";
  status_since: string | null;
}

export interface CarConfig {
  name: string;
  number: string;
  drivers: string[];
}

export interface RaceState {
  race_id: string | null;
  last_seq: number;
  now: string;
  config: { format: string; duration_min: number | null; cars: Record<CarId, CarConfig> };
  race: { started_at: string | null; ended_at: string | null };
  cars: Record<CarId, CarState>;
}
