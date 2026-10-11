import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ObservationSummary } from '../types';

const GREEN = '#16a34a';
const RED = '#dc2626';

function label(code: string): string {
  return code.replace(/_/g, ' ');
}

export function Charts({ summary }: { summary: ObservationSummary }) {
  const complianceData = [
    { name: 'Conformes', value: summary.compliant_observations },
    { name: 'Não conformes', value: summary.non_compliant_observations },
  ];

  return (
    <section className="charts-grid" aria-label="Gráficos">
      <div className="card">
        <h2>Observações por dia</h2>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={summary.by_day}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" fontSize={11} />
            <YAxis allowDecimals={false} fontSize={11} width={34} />
            <Tooltip />
            <Legend />
            <Bar
              dataKey="compliant"
              name="Conformes"
              stackId="obs"
              fill={GREEN}
            />
            <Bar
              dataKey="non_compliant"
              name="Não conformes"
              stackId="obs"
              fill={RED}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h2>Distribuição da conformidade</h2>
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie
              data={complianceData}
              dataKey="value"
              nameKey="name"
              innerRadius={58}
              outerRadius={92}
              paddingAngle={2}
            >
              <Cell fill={GREEN} />
              <Cell fill={RED} />
            </Pie>
            <Tooltip />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h2>Observações por tipo de evento</h2>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart
            data={summary.by_event_type.map((e) => ({
              ...e,
              name: label(e.event_code),
            }))}
            layout="vertical"
            margin={{ left: 8 }}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" allowDecimals={false} fontSize={11} />
            <YAxis
              type="category"
              dataKey="name"
              width={150}
              fontSize={11}
            />
            <Tooltip />
            <Bar dataKey="total" name="Observações" fill="#2563eb" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
