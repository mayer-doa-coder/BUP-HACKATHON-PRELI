import type { BatteryInput } from "../api/types";

interface Props {
  battery: BatteryInput;
  onChange: (battery: BatteryInput) => void;
}

const FIELDS: Array<[keyof BatteryInput, string, string]> = [
  ["capacity_kwh", "Capacity", "kWh"],
  ["initial_energy_kwh", "Initial energy", "kWh"],
  ["minimum_energy_kwh", "Minimum reserve", "kWh"],
  ["max_charge_kwh_per_hour", "Max charge rate", "kWh/h"],
  ["max_discharge_kwh_per_hour", "Max discharge rate", "kWh/h"],
];

/** Editor for the five battery parameters, sent as-is alongside the notes to the interpreter. */
export function BatteryEditor({ battery, onChange }: Props) {
  const update = (field: keyof BatteryInput, raw: string) => {
    onChange({ ...battery, [field]: raw === "" ? Number.NaN : Number(raw) });
  };

  return (
    <div className="field-group">
      <label>Battery</label>
      <div className="battery-grid">
        {FIELDS.map(([field, title, unit]) => (
          <div className="battery-field" key={field}>
            <span className="battery-field__label">{title}</span>
            <div className="battery-field__input">
              <input
                type="number"
                step="any"
                value={Number.isNaN(battery[field]) ? "" : battery[field]}
                onChange={(event) => update(field, event.target.value)}
              />
              <span className="battery-field__unit">{unit}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
