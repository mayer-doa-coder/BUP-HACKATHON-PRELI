import type { HourInput } from "../api/types";
import { formatHourRange } from "../utils/format";

interface Props {
  hours: HourInput[];
  onChange: (hours: HourInput[]) => void;
}

/**
 * The 24 hour entries of Problem Statement §7.2.
 *
 * The hour column is fixed rather than editable, which removes an entire class of contract
 * errors (duplicate, missing or out-of-range hours) from the UI: the request this builds always
 * has exactly one entry per hour 0..23.
 *
 * Cells carry a `data-label` so the stylesheet can stack them into cards on a phone.
 */
export function HoursEditor({ hours, onChange }: Props) {
  const update = (hour: number, field: keyof Omit<HourInput, "hour">, raw: string) => {
    const value = raw === "" ? Number.NaN : Number(raw);
    onChange(hours.map((entry) => (entry.hour === hour ? { ...entry, [field]: value } : entry)));
  };

  const sorted = [...hours].sort((a, b) => a.hour - b.hour);

  return (
    <div className="field-group">
      <span className="field-group__label">hours — 24 entries</span>
      <div className="table-wrap table-wrap--editor">
        <table className="data-table data-table--editor">
          <thead>
            <tr>
              <th scope="col">hour</th>
              <th scope="col">demand_kwh</th>
              <th scope="col">solar_kwh</th>
              <th scope="col">tariff_bdt_per_kwh</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((entry) => (
              <tr key={entry.hour}>
                <td data-label="hour" className="data-table__hour">
                  {formatHourRange(entry.hour)}
                </td>
                <td data-label="demand_kwh">
                  <input
                    id={`hour-demand_kwh-${entry.hour}`}
                    name={`hour_${entry.hour}_demand_kwh`}
                    type="number"
                    inputMode="decimal"
                    step="any"
                    aria-label={`demand_kwh for hour ${entry.hour}`}
                    value={Number.isNaN(entry.demand_kwh) ? "" : entry.demand_kwh}
                    onChange={(event) => update(entry.hour, "demand_kwh", event.target.value)}
                  />
                </td>
                <td data-label="solar_kwh">
                  <input
                    id={`hour-solar_kwh-${entry.hour}`}
                    name={`hour_${entry.hour}_solar_kwh`}
                    type="number"
                    inputMode="decimal"
                    step="any"
                    aria-label={`solar_kwh for hour ${entry.hour}`}
                    value={Number.isNaN(entry.solar_kwh) ? "" : entry.solar_kwh}
                    onChange={(event) => update(entry.hour, "solar_kwh", event.target.value)}
                  />
                </td>
                <td data-label="tariff_bdt_per_kwh">
                  <input
                    id={`hour-tariff_bdt_per_kwh-${entry.hour}`}
                    name={`hour_${entry.hour}_tariff_bdt_per_kwh`}
                    type="number"
                    inputMode="decimal"
                    step="any"
                    aria-label={`tariff_bdt_per_kwh for hour ${entry.hour}`}
                    value={Number.isNaN(entry.tariff_bdt_per_kwh) ? "" : entry.tariff_bdt_per_kwh}
                    onChange={(event) => update(entry.hour, "tariff_bdt_per_kwh", event.target.value)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
