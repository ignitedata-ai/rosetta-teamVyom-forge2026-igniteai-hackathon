/**
 * GoalSeekConvergence — line chart of the goal-seek search trajectory.
 * X axis: iteration index. Y axis: target cell's value at that iteration.
 * A dashed horizontal line marks the user's target_value.
 */

interface Props {
  x: number[];
  y: number[];
  targetLine?: number | null;
  yLabel?: string;
}

function formatNumber(v: number): string {
  if (!Number.isFinite(v)) return '—';
  if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString();
  if (Math.abs(v) >= 1) return v.toFixed(2);
  if (v === 0) return '0';
  return v.toFixed(4);
}

export default function GoalSeekConvergence({ x, y, targetLine, yLabel }: Props) {
  if (x.length === 0 || y.length === 0) return null;
  const width = 520;
  const height = 200;
  const padL = 50;
  const padR = 16;
  const padT = 24;
  const padB = 28;

  const xMin = Math.min(...x);
  const xMax = Math.max(...x);
  const ys = targetLine != null ? [...y, targetLine] : y;
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const ySpan = yMax - yMin || 1;
  const xSpan = xMax - xMin || 1;

  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const xScale = (v: number) => padL + ((v - xMin) / xSpan) * plotW;
  const yScale = (v: number) => padT + (1 - (v - yMin) / ySpan) * plotH;

  const path = y
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${xScale(x[i])} ${yScale(v)}`)
    .join(' ');

  return (
    <div className="mt-3 border border-[#e3e5ee] rounded-lg bg-[#f9f8fd] overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#e3e5ee] text-xs text-[#5a5c70]">
        <div className="flex items-center gap-3">
          <span className="text-[10px] uppercase tracking-[0.18em] text-[#0f1020] font-semibold">Goal-seek convergence</span>
          <span className="text-[#7a7d92]">
            {x.length} iterations · final {formatNumber(y[y.length - 1])}
          </span>
        </div>
      </div>
      <svg width={width} height={height} className="block">
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="#d0d3df" />
        <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="#d0d3df" />
        {targetLine != null && Number.isFinite(targetLine) && (
          <g>
            <line
              x1={padL}
              y1={yScale(targetLine)}
              x2={padL + plotW}
              y2={yScale(targetLine)}
              stroke="#f59e0b"
              strokeDasharray="4 4"
            />
            <text x={padL + plotW - 4} y={yScale(targetLine) - 4} fontSize="10" fill="#b45309" textAnchor="end">
              target {formatNumber(targetLine)}
            </text>
          </g>
        )}
        <path d={path} fill="none" stroke="#8243EA" strokeWidth="1.8" />
        {y.map((v, i) => (
          <circle key={i} cx={xScale(x[i])} cy={yScale(v)} r="3" fill="#5b21b6" />
        ))}
        <text x={padL - 6} y={padT + 4} fontSize="10" fill="#7a7d92" textAnchor="end">
          {formatNumber(yMax)}
        </text>
        <text x={padL - 6} y={padT + plotH} fontSize="10" fill="#7a7d92" textAnchor="end">
          {formatNumber(yMin)}
        </text>
        <text x={padL + plotW / 2} y={height - 6} fontSize="10" fill="#9a9caf" textAnchor="middle">
          iteration
        </text>
        {yLabel && (
          <text
            x={12}
            y={padT + plotH / 2}
            fontSize="10"
            fill="#9a9caf"
            transform={`rotate(-90 12 ${padT + plotH / 2})`}
            textAnchor="middle"
          >
            {yLabel.length > 24 ? yLabel.slice(0, 23) + '…' : yLabel}
          </text>
        )}
      </svg>
    </div>
  );
}
