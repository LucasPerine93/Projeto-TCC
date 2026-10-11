interface KpiCardProps {
  title: string;
  value: string;
  hint?: string;
  accent?: 'blue' | 'green' | 'red' | 'amber';
}

export function KpiCard({ title, value, hint, accent = 'blue' }: KpiCardProps) {
  return (
    <div className={`kpi ${accent}`}>
      <div className="kpi-title">{title}</div>
      <div className="kpi-value">{value}</div>
      {hint ? <div className="kpi-hint">{hint}</div> : null}
    </div>
  );
}
