import { useState } from "react";
import { optimizeEnergy } from "./api/client";
import type { OptimizeRequest, OptimizeResponse, SampleCase } from "./api/types";
import { createEmptyScenario, cloneScenario } from "./utils/scenario";
import { validateRequest } from "./utils/validation";
import { HealthBadge } from "./components/HealthBadge";
import { NotesEditor } from "./components/NotesEditor";
import { BatteryEditor } from "./components/BatteryEditor";
import { HoursEditor } from "./components/HoursEditor";
import { SamplePicker } from "./components/SamplePicker";
import { ResultsPanel } from "./components/ResultsPanel";
import { ErrorPanel } from "./components/ErrorPanel";

type RunState =
  | { status: "idle" }
  | { status: "running" }
  | { status: "done"; result: OptimizeResponse; request: OptimizeRequest }
  | { status: "error"; error: unknown };

export default function App() {
  const [request, setRequest] = useState<OptimizeRequest>(() => createEmptyScenario());
  const [validationProblems, setValidationProblems] = useState<string[]>([]);
  const [run, setRun] = useState<RunState>({ status: "idle" });

  const loadSample = (sample: SampleCase) => {
    setRequest(cloneScenario(sample.input));
    setValidationProblems([]);
    setRun({ status: "idle" });
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    const problems = validateRequest(request);
    setValidationProblems(problems);
    if (problems.length > 0) return;

    setRun({ status: "running" });
    try {
      const result = await optimizeEnergy(request);
      setRun({ status: "done", result, request });
    } catch (error) {
      setRun({ status: "error", error });
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>GridWise</h1>
          <p className="page-header__subtitle">
            Build a 24-hour scenario, send it to <code>POST /optimize-energy</code>, and read back the
            directive interpretation and the hourly plan.
          </p>
        </div>
        <HealthBadge />
      </header>

      <main className="layout">
        <form className="card scenario-form" onSubmit={handleSubmit}>
          <div className="card__title">Scenario</div>

          <SamplePicker onLoad={loadSample} />

          <div className="field-group">
            <label htmlFor="scenario-id">Scenario ID</label>
            <input
              id="scenario-id"
              type="text"
              value={request.scenario_id}
              onChange={(event) => setRequest({ ...request, scenario_id: event.target.value })}
            />
          </div>

          <NotesEditor
            notes={request.operator_notes}
            onChange={(operator_notes) => setRequest({ ...request, operator_notes })}
          />

          <BatteryEditor battery={request.battery} onChange={(battery) => setRequest({ ...request, battery })} />

          <HoursEditor hours={request.hours} onChange={(hours) => setRequest({ ...request, hours })} />

          {validationProblems.length > 0 && (
            <ul className="validation-list" role="alert">
              {validationProblems.map((problem, index) => (
                <li key={index}>{problem}</li>
              ))}
            </ul>
          )}

          <button type="submit" className="primary-button" disabled={run.status === "running"}>
            {run.status === "running" ? "Optimizing…" : "Run optimization"}
          </button>
        </form>

        <section className="card results-card">
          <div className="card__title">Result</div>
          {run.status === "idle" && (
            <p className="placeholder">Fill in a scenario (or load a sample) and run it to see the plan here.</p>
          )}
          {run.status === "running" && <p className="placeholder">Solving…</p>}
          {run.status === "error" && <ErrorPanel error={run.error} />}
          {run.status === "done" && <ResultsPanel result={run.result} request={run.request} />}
        </section>
      </main>
    </div>
  );
}
