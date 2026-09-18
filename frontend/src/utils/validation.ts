import {
  MAX_OPERATOR_NOTES,
  MIN_OPERATOR_NOTES,
  type OptimizeRequest,
} from "../api/types";

/**
 * Client-side pre-checks mirroring the backend's *structural* contract
 * (app/schemas/request.py) — not its semantic or guardrail rules. This
 * exists only so a scenario_id-typo or empty-note mistake shows up next to
 * the field instead of round-tripping to the server first. The backend
 * remains the sole source of truth: it re-validates everything regardless.
 */
export function validateRequest(request: OptimizeRequest): string[] {
  const problems: string[] = [];

  if (!request.scenario_id.trim()) {
    problems.push("Scenario ID must not be empty.");
  }

  const notes = request.operator_notes;
  if (notes.length < MIN_OPERATOR_NOTES || notes.length > MAX_OPERATOR_NOTES) {
    problems.push(`Provide between ${MIN_OPERATOR_NOTES} and ${MAX_OPERATOR_NOTES} operator notes.`);
  }
  notes.forEach((note, index) => {
    if (!note.trim()) {
      problems.push(`Operator note ${index + 1} must not be empty or whitespace only.`);
    }
  });

  for (const entry of request.hours) {
    if (!Number.isFinite(entry.demand_kwh)) problems.push(`Hour ${entry.hour}: demand_kwh must be a number.`);
    if (!Number.isFinite(entry.solar_kwh)) problems.push(`Hour ${entry.hour}: solar_kwh must be a number.`);
    if (!Number.isFinite(entry.tariff_bdt_per_kwh)) {
      problems.push(`Hour ${entry.hour}: tariff_bdt_per_kwh must be a number.`);
    }
  }

  const battery = request.battery;
  const batteryFields: Array<[keyof typeof battery, string]> = [
    ["capacity_kwh", "Capacity"],
    ["initial_energy_kwh", "Initial energy"],
    ["minimum_energy_kwh", "Minimum energy"],
    ["max_charge_kwh_per_hour", "Max charge rate"],
    ["max_discharge_kwh_per_hour", "Max discharge rate"],
  ];
  for (const [field, label] of batteryFields) {
    if (!Number.isFinite(battery[field])) {
      problems.push(`${label} must be a number.`);
    }
  }

  return problems;
}
