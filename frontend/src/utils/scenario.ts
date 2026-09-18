import { HOURS_IN_DAY, type OptimizeRequest } from "../api/types";

/** A blank 24-hour scenario, ready for a user to fill in or replace with a sample. */
export function createEmptyScenario(): OptimizeRequest {
  return {
    scenario_id: "CUSTOM-01",
    operator_notes: [""],
    hours: Array.from({ length: HOURS_IN_DAY }, (_, hour) => ({
      hour,
      demand_kwh: 0,
      solar_kwh: 0,
      tariff_bdt_per_kwh: 0,
    })),
    battery: {
      capacity_kwh: 200,
      initial_energy_kwh: 100,
      minimum_energy_kwh: 20,
      max_charge_kwh_per_hour: 50,
      max_discharge_kwh_per_hour: 50,
    },
  };
}

export function cloneScenario(request: OptimizeRequest): OptimizeRequest {
  return {
    scenario_id: request.scenario_id,
    operator_notes: [...request.operator_notes],
    hours: request.hours.map((entry) => ({ ...entry })),
    battery: { ...request.battery },
  };
}
