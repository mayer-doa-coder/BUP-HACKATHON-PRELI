import type { OptimizeRequest, OptimizeResponse } from "../api/types";
import { formatBdt, formatKwh } from "../utils/format";
import { StatTile } from "./StatTile";
import { DirectiveList } from "./DirectiveList";
import { HourlyPlanTable } from "./HourlyPlanTable";

interface Props {
  result: OptimizeResponse;
  request: OptimizeRequest;
}

/**
 * Shows exactly the response the Problem Statement §10 defines and nothing else:
 * scenario_id, directive_interpretation, hourly_plan, total_grid_kwh, total_cost_bdt,
 * peak_grid_kwh and plan_summary.
 */
export function ResultsPanel({ result, request }: Props) {
  return (
    <div className="results">
      <div className="scenario-echo">
        <span className="scenario-echo__label">scenario_id</span>
        <code className="scenario-echo__value">{result.scenario_id}</code>
      </div>

      <div className="stat-row">
        <StatTile label="total_grid_kwh" value={formatKwh(result.total_grid_kwh)} tone="accent" />
        <StatTile label="total_cost_bdt" value={formatBdt(result.total_cost_bdt)} tone="accent" />
        <StatTile label="peak_grid_kwh" value={formatKwh(result.peak_grid_kwh)} />
      </div>

      <section className="results-section">
        <h3>plan_summary</h3>
        <p className="plan-summary">{result.plan_summary}</p>
      </section>

      <section className="results-section">
        <h3>directive_interpretation</h3>
        <DirectiveList directives={result.directive_interpretation} notes={request.operator_notes} />
      </section>

      <section className="results-section">
        <h3>hourly_plan</h3>
        <HourlyPlanTable plan={result.hourly_plan} hours={request.hours} />
      </section>
    </div>
  );
}
