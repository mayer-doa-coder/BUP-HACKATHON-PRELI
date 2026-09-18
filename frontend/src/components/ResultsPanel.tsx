import { useState } from "react";
import type { OptimizeRequest, OptimizeResponse } from "../api/types";
import { formatBdt, formatKwh } from "../utils/format";
import { StatTile } from "./StatTile";
import { DirectiveList } from "./DirectiveList";
import { HourlyPlanChart } from "./HourlyPlanChart";
import { HourlyPlanTable } from "./HourlyPlanTable";

interface Props {
  result: OptimizeResponse;
  request: OptimizeRequest;
}

type View = "chart" | "table";

export function ResultsPanel({ result, request }: Props) {
  const [view, setView] = useState<View>("chart");
  const [showRaw, setShowRaw] = useState(false);

  return (
    <div className="results">
      <p className="plan-summary">{result.plan_summary}</p>

      <div className="stat-row">
        <StatTile label="Total grid import" value={formatKwh(result.total_grid_kwh)} tone="accent" />
        <StatTile label="Total cost" value={formatBdt(result.total_cost_bdt)} tone="accent" />
        <StatTile label="Peak grid import" value={formatKwh(result.peak_grid_kwh)} />
      </div>

      <section className="results-section">
        <h3>Directive interpretation</h3>
        <DirectiveList directives={result.directive_interpretation} notes={request.operator_notes} />
      </section>

      <section className="results-section">
        <div className="results-section__header">
          <h3>24-hour dispatch plan</h3>
          <div className="view-toggle">
            <button
              type="button"
              className={view === "chart" ? "view-toggle__button view-toggle__button--active" : "view-toggle__button"}
              onClick={() => setView("chart")}
            >
              Chart
            </button>
            <button
              type="button"
              className={view === "table" ? "view-toggle__button view-toggle__button--active" : "view-toggle__button"}
              onClick={() => setView("table")}
            >
              Table
            </button>
          </div>
        </div>
        {view === "chart" ? (
          <HourlyPlanChart plan={result.hourly_plan} hours={request.hours} />
        ) : (
          <HourlyPlanTable plan={result.hourly_plan} hours={request.hours} />
        )}
      </section>

      <details className="raw-json" open={showRaw} onToggle={(event) => setShowRaw(event.currentTarget.open)}>
        <summary>Raw response JSON</summary>
        <pre>{JSON.stringify(result, null, 2)}</pre>
      </details>
    </div>
  );
}
