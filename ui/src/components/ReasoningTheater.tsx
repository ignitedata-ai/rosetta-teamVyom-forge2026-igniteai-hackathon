/**
 * ReasoningTheater — the live cockpit shown while a question is in flight.
 *
 * Replaces the spinner/typing-dots placeholder. Animates through Rosetta's
 * 5-stage pipeline (Understand → Locate → Compute → Simulate → Verify) while
 * we wait for the backend response. Once the answer lands, the parent
 * collapses this component and renders the actual answer bubble; the user
 * can click "View reasoning →" on that bubble for the post-hoc modal which
 * shows the real per-stage state the backend computed.
 *
 * The theater is progress-driven rather than state-driven — we don't know
 * which stages are about to fire, so we simulate a cockpit walk-through on
 * a smooth eased clock. When the real response arrives, the parent hides us
 * and swaps in the answer.
 *
 * Mirrors 3001's ReasoningTheater with Rosetta stage labels.
 */

import { useEffect, useState } from 'react';

const STAGES: { id: string; symbol: string; label: string; message: string }[] = [
  {
    id: 'understand',
    symbol: 'U',
    label: 'Understand',
    message: 'Parsing the question · resolving follow-up references.',
  },
  {
    id: 'locate',
    symbol: 'L',
    label: 'Locate',
    message: 'Finding the cells, named ranges, and tables at issue.',
  },
  {
    id: 'compute',
    symbol: 'C',
    label: 'Compute',
    message: 'Reading values · tracing formulas · running analytics.',
  },
  {
    id: 'simulate',
    symbol: 'S',
    label: 'Simulate',
    message: 'Recomputing the workbook under counterfactual inputs.',
  },
  {
    id: 'verify',
    symbol: 'V',
    label: 'Verify',
    message: 'Cross-checking every cited number against the workbook.',
  },
];

// Target full-pipeline time in ms. When a real answer lands sooner, the
// parent just unmounts this component; the clock keeps going past 1.0 for
// long-running questions so the stepper never stalls awkwardly.
const STAGE_DURATION_MS = 900;

export default function ReasoningTheater({ question }: { question: string }) {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const start = performance.now();
    let raf = 0;
    const tick = () => {
      const elapsed = performance.now() - start;
      // Smooth ease-out-ish: asymptotically approach N as elapsed grows.
      const linear = elapsed / STAGE_DURATION_MS;
      const eased = STAGES.length * (1 - Math.exp(-linear / STAGES.length));
      setProgress(Math.min(eased, STAGES.length));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const N = STAGES.length;
  const clamped = Math.min(Math.max(progress, 0), N);
  const currentIdx = Math.min(Math.floor(clamped), N - 1);
  const activeNode = STAGES[currentIdx];
  const overallPct = (clamped / N) * 100;

  return (
    <div className="agentic-slide-up cockpit-glow-border relative overflow-hidden rounded-3xl border-2 bg-[linear-gradient(180deg,#fdfcff,#f3f1fb)] text-[#0f1020] shadow-[0_30px_80px_rgba(130,67,234,0.18)]">
      <div className="cockpit-grid-light absolute inset-0 opacity-100" />

      {/* Header */}
      <div className="relative flex items-center justify-between border-b border-[#e3e5ee] bg-white/85 px-6 py-3 backdrop-blur">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-[10px] font-bold uppercase text-white shadow-[0_8px_22px_rgba(130,67,234,0.45)]">
            DI
          </span>
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-[0.32em] text-[#7a7d92]">
              Agent engine · live
            </p>
            <p className="truncate text-sm font-semibold text-[#0f1020]">"{question}"</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="rounded-md bg-[#8243EA]/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-[#5b21b6]">
            Step {Math.min(currentIdx + 1, N)} / {N}
          </span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="relative h-1 overflow-hidden bg-[#eef0f7]">
        <div
          className="h-full bg-[linear-gradient(90deg,#8243EA,#2563EB)]"
          style={{ width: `${overallPct}%` }}
        />
      </div>

      {/* Stage nodes */}
      <div className="relative px-6 pt-6 pb-2">
        <div className="relative grid grid-cols-5 items-start gap-0">
          {STAGES.map((node, index) => {
            const activation = Math.max(0, Math.min(2, clamped - index));

            const pendingOpacity = Math.max(0, 1 - activation * 2.2);
            const activeOpacity =
              activation <= 1
                ? Math.min(1, activation * 2)
                : Math.max(0, (1.6 - activation) * 1.8);
            const doneOpacity = Math.max(0, Math.min(1, (activation - 0.85) * 2.2));

            const graySymbolOpacity = pendingOpacity;
            const whiteSymbolOpacity =
              activation <= 1
                ? Math.min(1, activation * 2.5)
                : Math.max(0, (1.4 - activation) * 2);
            const checkOpacity = Math.max(0, Math.min(1, (activation - 1) * 2.5));

            const scale = 0.92 + Math.min(activation, 1) * 0.08;
            const glowStrength = Math.min(
              1,
              activation <= 1 ? activation : Math.max(0, 1.8 - activation)
            );

            const labelDarkness = Math.min(1, activation * 1.5);
            const labelColor = `rgba(15, 16, 32, ${0.38 + labelDarkness * 0.62})`;
            const numberColor =
              activation >= 1
                ? `rgba(4, 120, 87, ${Math.min(1, (activation - 0.8) * 2)})`
                : activation > 0
                ? `rgba(91, 33, 182, ${Math.min(1, activation * 1.5)})`
                : '#cfd1de';

            const connectorFill = Math.max(0, Math.min(1, clamped - index));
            const connectorGreen = Math.max(0, Math.min(1, (clamped - index - 1) * 2));

            return (
              <div key={node.id} className="relative flex flex-col items-center">
                {index < STAGES.length - 1 && (
                  <div className="absolute left-1/2 top-7 z-0 h-1 w-full -translate-y-1/2 overflow-hidden rounded-full bg-[#e7e9f1]">
                    <div
                      className="absolute inset-y-0 left-0 bg-[linear-gradient(90deg,#8243EA,#2563EB)]"
                      style={{ width: `${connectorFill * 100}%` }}
                    />
                    <div
                      className="absolute inset-y-0 left-0 bg-emerald-500"
                      style={{ width: `${connectorFill * 100}%`, opacity: connectorGreen }}
                    />
                  </div>
                )}
                <div
                  className="relative z-10 h-14 w-14"
                  style={{ transform: `scale(${scale})`, transformOrigin: 'center' }}
                >
                  <div
                    className="absolute inset-0 rounded-2xl bg-white"
                    style={{ opacity: pendingOpacity, boxShadow: 'inset 0 0 0 2px #dadcea' }}
                  />
                  <div
                    className="absolute inset-0 rounded-2xl"
                    style={{
                      opacity: activeOpacity,
                      background: 'linear-gradient(135deg,#8243EA,#2563EB)',
                      boxShadow: `0 ${18 * glowStrength}px ${40 * glowStrength}px rgba(130,67,234,${0.45 * glowStrength})`,
                    }}
                  />
                  <div
                    className="absolute inset-0 rounded-2xl"
                    style={{
                      opacity: doneOpacity,
                      background: '#10b981',
                      boxShadow: `0 ${10 * doneOpacity}px ${22 * doneOpacity}px rgba(16,185,129,${0.32 * doneOpacity})`,
                    }}
                  />
                  <div className="relative flex h-full w-full items-center justify-center text-xl font-bold">
                    <span className="absolute text-[#9ea0b3]" style={{ opacity: graySymbolOpacity }}>
                      {node.symbol}
                    </span>
                    <span className="absolute text-white" style={{ opacity: whiteSymbolOpacity }}>
                      {node.symbol}
                    </span>
                    <span className="absolute text-white" style={{ opacity: checkOpacity }}>
                      ✓
                    </span>
                  </div>
                </div>
                <p
                  className="mt-2 font-mono text-[10px] font-bold"
                  style={{ color: numberColor }}
                >
                  0{index + 1}
                </p>
                <p
                  className="mt-0.5 text-[10px] font-bold uppercase tracking-[0.18em]"
                  style={{ color: labelColor }}
                >
                  {node.label}
                </p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Now-executing narration + timeline */}
      <div className="relative grid grid-cols-1 gap-0 lg:grid-cols-[1.2fr_1fr]">
        <div className="relative border-t border-[#e3e5ee] px-6 py-5">
          <p className="text-[10px] font-bold uppercase tracking-[0.32em] text-[#5b21b6]">
            Now executing
          </p>
          <div key={currentIdx} className="cockpit-trace mt-3 flex items-start gap-4">
            <div className="cockpit-active-pulse flex h-16 w-16 flex-none items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-2xl font-bold text-white">
              {activeNode.symbol}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xl font-semibold leading-tight text-[#0f1020]">
                {activeNode.label}
              </p>
              <p className="mt-1.5 text-[15px] leading-6 text-[#3d3f55]">
                {activeNode.message}
              </p>
            </div>
          </div>
          <div className="mt-4 flex items-center gap-2 text-[11px] text-[#7a7d92]">
            <div className="flex items-center gap-1">
              <span
                className="cockpit-dot h-1.5 w-1.5 rounded-full bg-[#8243EA]"
                style={{ animationDelay: '0s' }}
              />
              <span
                className="cockpit-dot h-1.5 w-1.5 rounded-full bg-[#8243EA]"
                style={{ animationDelay: '0.18s' }}
              />
              <span
                className="cockpit-dot h-1.5 w-1.5 rounded-full bg-[#8243EA]"
                style={{ animationDelay: '0.36s' }}
              />
            </div>
            <span className="uppercase tracking-[0.18em]">Reasoning</span>
          </div>
        </div>

        <div className="relative border-t border-[#e3e5ee] bg-white/70 px-6 py-5 lg:border-l">
          <p className="text-[10px] font-bold uppercase tracking-[0.32em] text-[#7a7d92]">
            Timeline
          </p>
          <ol className="mt-3 space-y-2.5">
            {STAGES.map((node, index) => {
              const activation = Math.max(0, Math.min(2, clamped - index));
              const itemOpacity = 0.35 + Math.min(1, activation * 1.5) * 0.65;
              const badgePending = Math.max(0, 1 - activation * 2);
              const badgeActive =
                activation <= 1
                  ? Math.min(1, activation * 2)
                  : Math.max(0, (1.4 - activation) * 2);
              const badgeDone = Math.max(0, Math.min(1, (activation - 1) * 2));
              const labelCol = activation > 0.3 ? '#5b21b6' : '#9ea0b3';
              const bodyCol = `rgba(61, 63, 85, ${0.4 + Math.min(1, activation * 1.2) * 0.6})`;
              return (
                <li key={node.id} className="flex gap-3" style={{ opacity: itemOpacity }}>
                  <div className="relative mt-0.5 h-6 w-6 flex-none">
                    <span
                      className="absolute inset-0 flex items-center justify-center rounded-md border-2 border-dashed border-[#cfd1de] text-[10px] font-bold text-[#cfd1de]"
                      style={{ opacity: badgePending }}
                    >
                      {index + 1}
                    </span>
                    <span
                      className="absolute inset-0 flex items-center justify-center rounded-md bg-[#8243EA]/15 text-[10px] font-bold text-[#5b21b6]"
                      style={{ opacity: badgeActive }}
                    >
                      {index + 1}
                    </span>
                    <span
                      className="absolute inset-0 flex items-center justify-center rounded-md bg-emerald-500 text-[10px] font-bold text-white"
                      style={{ opacity: badgeDone }}
                    >
                      ✓
                    </span>
                  </div>
                  <div className="min-w-0">
                    <p
                      className="text-[10px] font-bold uppercase tracking-[0.18em]"
                      style={{ color: labelCol }}
                    >
                      {node.label}
                    </p>
                    <p className="text-[12px] leading-snug" style={{ color: bodyCol }}>
                      {node.message}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </div>
  );
}
