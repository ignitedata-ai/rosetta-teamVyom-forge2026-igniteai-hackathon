/**
 * AnalyticsChart — dispatches on chart_data.type to the right chart component.
 * Single entry point the Dashboard uses, so adding a new chart kind later
 * means adding one case here rather than touching Dashboard.
 */

import TornadoChart from './TornadoChart';
import GoalSeekConvergence from './GoalSeekConvergence';

export interface ChartData {
  type: string;
  x?: (string | number)[];
  y?: number[];
  labels?: string[];
  high?: number[];
  low?: number[];
  baseline?: number;
  target_line?: number | null;
  x_label?: string;
  y_label?: string;
}

export default function AnalyticsChart({ chart }: { chart: ChartData | null | undefined }) {
  if (!chart || !chart.type) return null;

  if (chart.type === 'tornado') {
    const labels = chart.labels ?? [];
    const high = chart.high ?? [];
    const low = chart.low ?? [];
    const data = labels.map((label, i) => ({ label, high: high[i] ?? 0, low: low[i] ?? 0 }));
    return (
      <TornadoChart
        data={data}
        baseline={chart.baseline ?? 0}
        yLabel={chart.y_label}
      />
    );
  }

  if (chart.type === 'line') {
    // Convergence / time-series line — numeric x preferred; if strings, use index
    const xRaw = chart.x ?? [];
    const y = chart.y ?? [];
    const xNumeric = xRaw.every((v) => typeof v === 'number')
      ? (xRaw as number[])
      : xRaw.map((_, i) => i);
    // If it's a goal-seek convergence, we expect `target_line`
    if (chart.target_line !== undefined) {
      return (
        <GoalSeekConvergence
          x={xNumeric}
          y={y}
          targetLine={chart.target_line}
          yLabel={chart.y_label}
        />
      );
    }
    // Generic time-series: reuse convergence renderer without target line
    return <GoalSeekConvergence x={xNumeric} y={y} yLabel={chart.y_label} />;
  }

  if (chart.type === 'bar') {
    // Simple bar chart — pure SVG inline
    const labels = (chart.x ?? []).map(String);
    const values = chart.y ?? [];
    const maxV = Math.max(1e-9, ...values.map((v) => Math.abs(v)));
    const width = 520;
    const barH = 22;
    const labelW = 140;
    const valueW = 64;
    const plotW = width - labelW - valueW - 12;
    const height = values.length * barH + 36;
    return (
      <div className="mt-3 border border-slate-700 rounded-lg bg-slate-950/60 overflow-hidden">
        <div className="px-3 py-2 border-b border-slate-700 text-xs text-slate-300 font-semibold">
          {chart.y_label ?? 'value'} by {chart.x_label ?? 'group'}
        </div>
        <svg width={width} height={height} className="block">
          {values.map((v, i) => {
            const y = 20 + i * barH;
            const w = (Math.abs(v) / maxV) * plotW;
            return (
              <g key={i}>
                <text x={labelW - 8} y={y + 14} fontSize="11" fill="#cbd5e1" textAnchor="end" fontFamily="monospace">
                  {labels[i]?.length > 18 ? labels[i].slice(0, 17) + '…' : labels[i]}
                </text>
                <rect x={labelW} y={y} width={w} height={16} fill="#818cf8" opacity={0.85} />
                <text x={labelW + w + 4} y={y + 13} fontSize="10" fill="#94a3b8">
                  {Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : v.toFixed(2)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    );
  }

  return null;
}
