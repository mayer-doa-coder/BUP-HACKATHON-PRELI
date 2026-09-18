interface Props {
  label: string;
  value: string;
  tone?: "default" | "accent";
}

export function StatTile({ label, value, tone = "default" }: Props) {
  return (
    <div className={`stat-tile stat-tile--${tone}`}>
      <span className="stat-tile__label">{label}</span>
      <span className="stat-tile__value">{value}</span>
    </div>
  );
}
