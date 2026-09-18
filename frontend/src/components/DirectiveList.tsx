import type { DirectiveInterpretation } from "../api/types";
import { formatHourRange } from "../utils/format";

interface Props {
  directives: DirectiveInterpretation[];
  notes: string[];
}

const TYPE_LABEL: Record<DirectiveInterpretation["directive_type"], string> = {
  solar_reduction: "Solar reduction",
  minimum_battery_reserve: "Minimum battery reserve",
  no_charge_window: "No-charge window",
  no_discharge_window: "No-discharge window",
  max_grid_window: "Grid import cap",
  no_op: "No operation",
};

function hoursLabel(hours: number[]): string {
  if (hours.length === 0) return "";
  // Collapse consecutive runs (e.g. [13,14,15] -> "1–4 PM") for readability.
  const runs: Array<[number, number]> = [];
  let start = hours[0];
  let prev = hours[0];
  for (const hour of hours.slice(1)) {
    if (hour === prev + 1) {
      prev = hour;
      continue;
    }
    runs.push([start, prev]);
    start = hour;
    prev = hour;
  }
  runs.push([start, prev]);

  return runs
    .map(([from, to]) => (from === to ? formatHourRange(from) : `${formatHourRange(from).split("–")[0]}–${formatHourRange(to).split("–")[1]}`))
    .join(", ");
}

function adjustmentSummary(directive: DirectiveInterpretation): string | null {
  switch (directive.directive_type) {
    case "solar_reduction":
      return `Solar usable at ${(directive.structured_adjustment.factor * 100).toFixed(0)}% during ${hoursLabel(directive.structured_adjustment.hours)}`;
    case "minimum_battery_reserve":
      return `Reserve ≥ ${directive.structured_adjustment.minimum_energy_kwh} kWh during ${hoursLabel(directive.structured_adjustment.hours)}`;
    case "no_charge_window":
      return `No charging during ${hoursLabel(directive.structured_adjustment.hours)}`;
    case "no_discharge_window":
      return `No discharging during ${hoursLabel(directive.structured_adjustment.hours)}`;
    case "max_grid_window":
      return `Grid import ≤ ${directive.structured_adjustment.max_grid_kwh} kWh during ${hoursLabel(directive.structured_adjustment.hours)}`;
    case "no_op":
      return null;
  }
}

export function DirectiveList({ directives, notes }: Props) {
  return (
    <div className="directive-list">
      {directives.map((directive) => (
        <div
          className={`directive-card ${directive.applies ? "directive-card--applies" : "directive-card--no-op"}`}
          key={directive.note_index}
        >
          <div className="directive-card__header">
            <span className="directive-card__index">Note {directive.note_index + 1}</span>
            <span className={`directive-card__type ${directive.applies ? "" : "directive-card__type--muted"}`}>
              {TYPE_LABEL[directive.directive_type]}
            </span>
          </div>
          <p className="directive-card__note">“{notes[directive.note_index] ?? ""}”</p>
          {adjustmentSummary(directive) && (
            <p className="directive-card__adjustment">{adjustmentSummary(directive)}</p>
          )}
          {directive.explanation && <p className="directive-card__explanation">{directive.explanation}</p>}
        </div>
      ))}
    </div>
  );
}
