import type { HourInput, HourPlan } from "../api/types";
import { formatHourRange } from "../utils/format";

interface Props {
  plan: HourPlan[];
  hours: HourInput[];
}

const ACTION_LABEL: Record<HourPlan["battery_action"], string> = {
  charge: "Charge",
  discharge: "Discharge",
  idle: "Idle",
};

/**
 * The 24 plan entries, showing exactly the fields of Problem Statement §10.3.
 *
 * Each cell carries a `data-label`, which is what lets the stylesheet fold the table into
 * stacked cards on a narrow screen instead of forcing a horizontal scroll.
 */
export function HourlyPlanTable({ plan, hours }: Props) {
  const demandByHour = new Map(hours.map((entry) => [entry.hour, entry.demand_kwh]));

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">hour</th>
            <th scope="col">demand</th>
            <th scope="col">grid_kwh</th>
            <th scope="col">solar_used_kwh</th>
            <th scope="col">battery_action</th>
            <th scope="col">battery_energy_after_kwh</th>
          </tr>
        </thead>
        <tbody>
          {plan.map((entry) => (
            <tr key={entry.hour}>
              <td data-label="hour" className="data-table__hour">
                {formatHourRange(entry.hour)}
              </td>
              <td data-label="demand">{(demandByHour.get(entry.hour) ?? 0).toFixed(1)}</td>
              <td data-label="grid_kwh">{entry.grid_kwh.toFixed(2)}</td>
              <td data-label="solar_used_kwh">{entry.solar_used_kwh.toFixed(2)}</td>
              <td data-label="battery_action">
                <span className={`action-pill action-pill--${entry.battery_action}`}>
                  {ACTION_LABEL[entry.battery_action]}
                  {entry.battery_action !== "idle" ? ` · ${entry.battery_kwh.toFixed(2)} kWh` : ""}
                </span>
              </td>
              <td data-label="battery_energy_after_kwh">{entry.battery_energy_after_kwh.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
