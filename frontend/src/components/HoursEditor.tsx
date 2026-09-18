import type { HourInput } from "../api/types";
import { formatHourRange } from "../utils/format";

interface Props {
  hours: HourInput[];
  onChange: (hours: HourInput[]) => void;
}

/**
 * The 24-hour demand/solar/tariff table. The hour column is fixed (not editable), which
 * removes an entire class of contract errors (duplicate/missing/out-of-range hours) from
 * the UI entirely — the request this builds always has exactly one entry per hour 0..23.
 */
export function HoursEditor({ hours, onChange }: Props) {
  const update = (hour: number, field: keyof Omit<HourInput, "hour">, raw: string) => {
    const value = raw === "" ? Number.NaN : Number(raw);
    onChange(hours.map((entry) => (entry.hour === hour ? { ...entry, [field]: value } : entry)));
  };

  const sorted = [...hours].sort((a, b) => a.hour - b.hour);

  return (
    <div className="field-group">
      <label>24-hour scenario</label>
      <div className="hours-table-wrap">
        <table className="hours-table">
          <thead>
            <tr>
              <th>Hour</th>
              <th>Demand (kWh)</th>
              <th>Solar (kWh)</th>
              <th>Tariff (৳/kWh)</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((entry) => (
              <tr key={entry.hour}>
                <td className="hours-table__hour">{formatHourRange(entry.hour)}</td>
                <td>
                  <input
                    type="number"
                    step="any"
                    value={Number.isNaN(entry.demand_kwh) ? "" : entry.demand_kwh}
                    onChange={(event) => update(entry.hour, "demand_kwh", event.target.value)}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    step="any"
                    value={Number.isNaN(entry.solar_kwh) ? "" : entry.solar_kwh}
                    onChange={(event) => update(entry.hour, "solar_kwh", event.target.value)}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    step="any"
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
