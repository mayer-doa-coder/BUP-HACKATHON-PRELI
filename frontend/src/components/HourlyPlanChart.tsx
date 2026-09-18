import type { HourInput, HourPlan } from "../api/types";
import { formatHour } from "../utils/format";

interface Props {
  plan: HourPlan[];
  hours: HourInput[];
}

const WIDTH = 760;
const HEIGHT = 320;
const MARGIN = { top: 16, right: 52, bottom: 28, left: 48 };
const PLOT_W = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_H = HEIGHT - MARGIN.top - MARGIN.bottom;
const GRIDLINES = 4;

const ACTION_COLOR: Record<HourPlan["battery_action"], string> = {
  charge: "var(--action-charge)",
  discharge: "var(--action-discharge)",
  idle: "var(--action-idle)",
};

/**
 * Hand-rolled SVG chart (no charting library): stacked grid+solar bars against a demand
 * reference line, plus battery state-of-charge on a secondary axis with per-hour action
 * color coding. Self-contained so the frontend has zero extra runtime dependencies.
 */
export function HourlyPlanChart({ plan, hours }: Props) {
  const demandByHour = new Map(hours.map((entry) => [entry.hour, entry.demand_kwh]));
  const sorted = [...plan].sort((a, b) => a.hour - b.hour);

  const leftMax =
    Math.max(
      1,
      ...sorted.map((entry) => entry.grid_kwh + entry.solar_used_kwh),
      ...sorted.map((entry) => demandByHour.get(entry.hour) ?? 0),
    ) * 1.15;

  const rightMax = Math.max(1, ...sorted.map((entry) => entry.battery_energy_after_kwh)) * 1.15;

  const groupWidth = PLOT_W / sorted.length;
  const barWidth = groupWidth * 0.55;

  const xCenter = (index: number) => MARGIN.left + index * groupWidth + groupWidth / 2;
  const yLeft = (value: number) => MARGIN.top + PLOT_H - (value / leftMax) * PLOT_H;
  const yRight = (value: number) => MARGIN.top + PLOT_H - (value / rightMax) * PLOT_H;

  const batteryPoints = sorted.map((entry, index) => `${xCenter(index)},${yRight(entry.battery_energy_after_kwh)}`).join(" ");

  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="chart" role="img" aria-label="24-hour dispatch plan">
        {/* horizontal gridlines + left-axis labels (grid + solar, kWh) */}
        {Array.from({ length: GRIDLINES + 1 }, (_, i) => {
          const value = (leftMax / GRIDLINES) * i;
          const y = yLeft(value);
          return (
            <g key={i}>
              <line x1={MARGIN.left} x2={WIDTH - MARGIN.right} y1={y} y2={y} className="chart__gridline" />
              <text x={MARGIN.left - 8} y={y} className="chart__axis-label chart__axis-label--left" textAnchor="end" dominantBaseline="middle">
                {value.toFixed(0)}
              </text>
            </g>
          );
        })}

        {/* right-axis labels (battery energy, kWh) */}
        {Array.from({ length: GRIDLINES + 1 }, (_, i) => {
          const value = (rightMax / GRIDLINES) * i;
          const y = yRight(value);
          return (
            <text
              key={i}
              x={WIDTH - MARGIN.right + 8}
              y={y}
              className="chart__axis-label chart__axis-label--right"
              textAnchor="start"
              dominantBaseline="middle"
            >
              {value.toFixed(0)}
            </text>
          );
        })}

        {/* stacked bars: grid (bottom) + solar used (top) */}
        {sorted.map((entry, index) => {
          const x = xCenter(index) - barWidth / 2;
          const gridTop = yLeft(entry.grid_kwh);
          const solarTop = yLeft(entry.grid_kwh + entry.solar_used_kwh);
          const bottom = MARGIN.top + PLOT_H;
          return (
            <g key={entry.hour}>
              <rect x={x} y={gridTop} width={barWidth} height={Math.max(0, bottom - gridTop)} className="chart__bar chart__bar--grid" />
              <rect
                x={x}
                y={solarTop}
                width={barWidth}
                height={Math.max(0, gridTop - solarTop)}
                className="chart__bar chart__bar--solar"
              />
            </g>
          );
        })}

        {/* demand reference line */}
        <polyline
          points={sorted.map((entry, index) => `${xCenter(index)},${yLeft(demandByHour.get(entry.hour) ?? 0)}`).join(" ")}
          className="chart__demand-line"
        />

        {/* battery state of charge, colored by the hour's action */}
        <polyline points={batteryPoints} className="chart__battery-line" />
        {sorted.map((entry, index) => (
          <circle
            key={entry.hour}
            cx={xCenter(index)}
            cy={yRight(entry.battery_energy_after_kwh)}
            r={3.2}
            fill={ACTION_COLOR[entry.battery_action]}
            className="chart__battery-dot"
          >
            <title>
              {formatHour(entry.hour)}: {entry.battery_action} · {entry.battery_energy_after_kwh.toFixed(2)} kWh stored
            </title>
          </circle>
        ))}

        {/* x-axis: every 3rd hour to avoid crowding */}
        {sorted.map((entry, index) =>
          index % 3 === 0 ? (
            <text
              key={entry.hour}
              x={xCenter(index)}
              y={HEIGHT - MARGIN.bottom + 16}
              className="chart__axis-label chart__axis-label--x"
              textAnchor="middle"
            >
              {formatHour(entry.hour)}
            </text>
          ) : null,
        )}
      </svg>

      <div className="chart-legend">
        <span className="chart-legend__item">
          <span className="chart-legend__swatch chart-legend__swatch--grid" /> Grid import
        </span>
        <span className="chart-legend__item">
          <span className="chart-legend__swatch chart-legend__swatch--solar" /> Solar used
        </span>
        <span className="chart-legend__item">
          <span className="chart-legend__swatch chart-legend__swatch--demand" /> Demand (reference)
        </span>
        <span className="chart-legend__item">
          <span className="chart-legend__swatch chart-legend__swatch--battery" /> Battery state of charge
        </span>
        <span className="chart-legend__item">
          <span className="chart-legend__dot chart-legend__dot--charge" /> Charging
        </span>
        <span className="chart-legend__item">
          <span className="chart-legend__dot chart-legend__dot--discharge" /> Discharging
        </span>
      </div>
    </div>
  );
}
