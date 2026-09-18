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

export function HourlyPlanTable({ plan, hours }: Props) {
  const demandByHour = new Map(hours.map((entry) => [entry.hour, entry.demand_kwh]));

  return (
    <div className="hours-table-wrap">
      <table className="hours-table hours-table--plan">
        <thead>
          <tr>
            <th>Hour</th>
            <th>Demand</th>
            <th>Grid</th>
            <th>Solar used</th>
            <th>Battery</th>
            <th>Energy after</th>
          </tr>
        </thead>
        <tbody>
          {plan.map((entry) => (
            <tr key={entry.hour}>
              <td className="hours-table__hour">{formatHourRange(entry.hour)}</td>
              <td>{(demandByHour.get(entry.hour) ?? 0).toFixed(1)}</td>
              <td>{entry.grid_kwh.toFixed(2)}</td>
              <td>{entry.solar_used_kwh.toFixed(2)}</td>
              <td>
                <span className={`action-pill action-pill--${entry.battery_action}`}>
                  {ACTION_LABEL[entry.battery_action]}
                  {entry.battery_action !== "idle" ? ` · ${entry.battery_kwh.toFixed(2)} kWh` : ""}
                </span>
              </td>
              <td>{entry.battery_energy_after_kwh.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
