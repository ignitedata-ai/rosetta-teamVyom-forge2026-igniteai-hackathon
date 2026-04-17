/**
 * TornadoChart — horizontal diverging bars, one per input, ranked by |impact|.
 * Canonical visualisation for sensitivity analysis: each input's low/high
 * perturbation swings the target left/right of a baseline axis.
 */

interface TornadoDatum {
  label: string;
  low: number;   // Δ at input × (1 - delta)
  high: number;  // Δ at input × (1 + delta)
}

interface Props {
  data: TornadoDatum[];
  baseline: number;
  yLabel?: string;
  deltaPct?: number;
}

function formatNumber(v: number): string {
  if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString();
  if (Math.abs(v) >= 1) return v.toFixed(2);
  if (v === 0) return '0';
  return v.toFixed(4);
}

export default function TornadoChart({ data, baseline, yLabel, deltaPct }: Props) {
  const rows = data.slice(0, 12); // keep it scannable
  const maxAbs = Math.max(
    0.00001,
    ...rows.flatMap((r) => [Math.abs(r.low), Math.abs(r.high)])
  );
  const rowH = 28;
  const pad = 110;
  const width = 520;
  const innerW = width - pad - 12;
  const height = rows.length * rowH + 36;

  return (
    <div className="mt-3 border border-slate-700 rounded-lg bg-slate-950/60 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700 text-xs text-slate-300">
        <div className="flex items-center gap-3">
          <span className="font-semibold">Sensitivity — tornado</span>
          <span className="text-slate-500">
            baseline {yLabel ?? 'target'} = {formatNumber(baseline)}
            {deltaPct != null ? ` · ±${deltaPct.toFixed(0)}% inputs` : ''}
          </span>
        </div>
      </div>
      <svg width={width} height={height} className="block">
        {/* Baseline axis */}
        <line
          x1={pad + innerW / 2}
          y1={18}
          x2={pad + innerW / 2}
          y2={height - 12}
          stroke="#475569"
          strokeDasharray="3 3"
        />
        {rows.map((r, i) => {
          const y = 24 + i * rowH;
          const lowW = (Math.abs(r.low) / maxAbs) * (innerW / 2 - 4);
          const highW = (Math.abs(r.high) / maxAbs) * (innerW / 2 - 4);
          const center = pad + innerW / 2;
          return (
            <g key={r.label}>
              <text
                x={pad - 6}
                y={y + 14}
                textAnchor="end"
                fontSize="11"
                fill="#cbd5e1"
                fontFamily="monospace"
              >
                {r.label.length > 16 ? r.label.slice(0, 15) + '…' : r.label}
              </text>
              {/* Low side */}
              <rect
                x={center - lowW}
                y={y}
                width={lowW}
                height={18}
                fill={r.low < 0 ? '#ef4444' : '#22c55e'}
                opacity={0.85}
              />
              {/* High side */}
              <rect
                x={center}
                y={y}
                width={highW}
                height={18}
                fill={r.high > 0 ? '#22c55e' : '#ef4444'}
                opacity={0.85}
              />
              {/* Labels outside the bars */}
              <text x={center - lowW - 4} y={y + 14} textAnchor="end" fontSize="10" fill="#94a3b8">
                {formatNumber(r.low)}
              </text>
              <text x={center + highW + 4} y={y + 14} textAnchor="start" fontSize="10" fill="#94a3b8">
                {formatNumber(r.high)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
