/**
 * Types mirroring the backend's canonical schemas exactly:
 *   app/schemas/request.py, app/schemas/response.py, app/schemas/directive.py
 *
 * Kept hand-written and 1:1 with those Pydantic models rather than generated,
 * since the backend has no OpenAPI-export step yet. If the backend contract
 * changes, update here to match — never the other way around.
 */

export const HOURS_IN_DAY = 24;
export const MIN_OPERATOR_NOTES = 1;
export const MAX_OPERATOR_NOTES = 3;

// ---------------------------------------------------------------- request

export interface HourInput {
  hour: number; // 0..23
  demand_kwh: number;
  solar_kwh: number;
  tariff_bdt_per_kwh: number;
}

export interface BatteryInput {
  capacity_kwh: number;
  initial_energy_kwh: number;
  minimum_energy_kwh: number;
  max_charge_kwh_per_hour: number;
  max_discharge_kwh_per_hour: number;
}

export interface OptimizeRequest {
  scenario_id: string;
  operator_notes: string[];
  hours: HourInput[];
  battery: BatteryInput;
}

// ------------------------------------------------------------- directives

export type DirectiveType =
  | "solar_reduction"
  | "minimum_battery_reserve"
  | "no_charge_window"
  | "no_discharge_window"
  | "max_grid_window"
  | "no_op";

export interface SolarAdjustment {
  hours: number[];
  factor: number;
}

export interface ReserveAdjustment {
  hours: number[];
  minimum_energy_kwh: number;
}

export interface HourSetAdjustment {
  hours: number[];
}

export interface GridCapAdjustment {
  hours: number[];
  max_grid_kwh: number;
}

interface DirectiveBase {
  note_index: number;
  applies: boolean;
  explanation: string;
}

export interface SolarReductionDirective extends DirectiveBase {
  directive_type: "solar_reduction";
  applies: true;
  structured_adjustment: SolarAdjustment;
}

export interface MinimumBatteryReserveDirective extends DirectiveBase {
  directive_type: "minimum_battery_reserve";
  applies: true;
  structured_adjustment: ReserveAdjustment;
}

export interface NoChargeWindowDirective extends DirectiveBase {
  directive_type: "no_charge_window";
  applies: true;
  structured_adjustment: HourSetAdjustment;
}

export interface NoDischargeWindowDirective extends DirectiveBase {
  directive_type: "no_discharge_window";
  applies: true;
  structured_adjustment: HourSetAdjustment;
}

export interface MaxGridWindowDirective extends DirectiveBase {
  directive_type: "max_grid_window";
  applies: true;
  structured_adjustment: GridCapAdjustment;
}

export interface NoOpDirective extends DirectiveBase {
  directive_type: "no_op";
  applies: false;
  structured_adjustment: null;
}

export type DirectiveInterpretation =
  | SolarReductionDirective
  | MinimumBatteryReserveDirective
  | NoChargeWindowDirective
  | NoDischargeWindowDirective
  | MaxGridWindowDirective
  | NoOpDirective;

// ----------------------------------------------------------------- response

export type BatteryAction = "charge" | "discharge" | "idle";

export interface HourPlan {
  hour: number;
  grid_kwh: number;
  solar_used_kwh: number;
  battery_action: BatteryAction;
  battery_kwh: number;
  battery_energy_after_kwh: number;
}

export interface OptimizeResponse {
  scenario_id: string;
  directive_interpretation: DirectiveInterpretation[];
  hourly_plan: HourPlan[];
  total_grid_kwh: number;
  total_cost_bdt: number;
  peak_grid_kwh: number;
  plan_summary: string;
}

// -------------------------------------------------------------------- errors

/** The single error envelope used by every failure path (app/api/errors.py). */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    correlation_id: string;
    details?: string[];
  };
}

// -------------------------------------------------------------------- samples

/** A trimmed public sample case, for the "load example" picker. Not judge data. */
export interface SampleCase {
  id: string;
  label: string;
  input: OptimizeRequest;
}
