import { useEffect, useState } from "react";
import type { SampleCase } from "../api/types";

interface Props {
  onLoad: (sample: SampleCase) => void;
}

/**
 * Loads the organizer's public sample pack (trimmed to id/label/input, copied at
 * `public/samples.json`) so a user can try the UI without hand-typing 24 hourly rows.
 * These are the public examples the organizers themselves publish — not hidden judge
 * data — and this picker is demo-only, never consulted by the backend.
 */
export function SamplePicker({ onLoad }: Props) {
  const [samples, setSamples] = useState<SampleCase[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/samples.json")
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json() as Promise<SampleCase[]>;
      })
      .then(setSamples)
      .catch(() => setError(true));
  }, []);

  const handleSelect = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const id = event.target.value;
    const sample = samples?.find((entry) => entry.id === id);
    if (sample) onLoad(sample);
    event.target.value = "";
  };

  if (error) return null;

  return (
    <div className="sample-picker">
      <label htmlFor="sample-select">Load a public sample case</label>
      <select id="sample-select" defaultValue="" onChange={handleSelect} disabled={!samples}>
        <option value="" disabled>
          {samples ? "Choose a case…" : "Loading…"}
        </option>
        {samples?.map((sample) => (
          <option key={sample.id} value={sample.id}>
            {sample.id} — {sample.label}
          </option>
        ))}
      </select>
    </div>
  );
}
