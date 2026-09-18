export function formatKwh(value: number, decimals = 2): string {
  return `${value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })} kWh`;
}

export function formatBdt(value: number, decimals = 2): string {
  return `৳${value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`;
}

export function formatHour(hour: number): string {
  const period = hour < 12 ? "AM" : "PM";
  const display = hour % 12 === 0 ? 12 : hour % 12;
  return `${display} ${period}`;
}

export function formatHourRange(hour: number): string {
  return `${formatHour(hour)}–${formatHour((hour + 1) % 24)}`;
}
