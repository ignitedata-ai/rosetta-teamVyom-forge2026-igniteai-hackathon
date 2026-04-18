/**
 * ReasoningModal — post-hoc defensibility panel.
 *
 * Opens from the "View reasoning →" link under every answer bubble. Renders:
 *   1. Header — microlabel, quoted question, Close
 *   2. Pipeline stepper — 5 stages (green tick = ran, amber = failed,
 *      dashed grey = skipped)
 *   3. Four KPI cards — Verdict, Latency, Cells referenced, Steps
 *   4. Tab row — [View Details | How it Works]
 *      • View Details (default): the full verbose answer, markdown-rendered
 *      • How it Works: the numbered narrative from the backend trace
 *
 * Mirrors the 3001 design one-to-one except for:
 *   - Two tabs instead of three (Source Rows / Executed Code dropped)
 *   - "Cells" replaces "Source rows" on the third KPI card
 *
 * Dismiss: Esc, Close button, click outside the panel.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import AnswerMarkdown from './AnswerMarkdown';
import type {
  AskQuestionResponse,
  ReasoningStageState,
  ReasoningTrace,
} from '../api/excelAgent';

type Tab = 'details' | 'howItWorks';

const STORAGE_KEY = 'rosetta.reasoningModal.tab';

function readStoredTab(): Tab {
  if (typeof window === 'undefined') return 'details';
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (raw === 'howItWorks') return 'howItWorks';
  return 'details';
}

interface Props {
  open: boolean;
  question: string;
  response: AskQuestionResponse | null;
  onClose: () => void;
}

export default function ReasoningModal({ open, question, response, onClose }: Props) {
  const [tab, setTab] = useState<Tab>(() => readStoredTab());
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, tab);
    }
  }, [tab]);

  // Esc to close + scroll lock
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  const onBackdrop = useCallback(
    (e: React.MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) onClose();
    },
    [onClose]
  );

  if (!open || typeof document === 'undefined' || !response) return null;

  const trace = response.reasoning_trace ?? null;
  const detailed =
    response.detailed_answer ??
    (typeof response.answer === 'string' ? response.answer : '') ??
    '';

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onBackdrop}
    >
      <div
        ref={panelRef}
        className="agentic-slide-up relative flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-3xl border-2 border-[#e3e5ee] bg-[linear-gradient(180deg,#fdfcff,#f3f1fb)] text-[#0f1020] shadow-[0_40px_100px_rgba(0,0,0,0.35)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cockpit-grid-light pointer-events-none absolute inset-0 opacity-100" />

        {/* Header */}
        <div className="relative flex items-center justify-between border-b border-[#e3e5ee] bg-white/85 px-6 py-4 backdrop-blur">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-[10px] font-bold uppercase text-white shadow-[0_8px_22px_rgba(130,67,234,0.45)]">
              DI
            </span>
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-[0.32em] text-[#7a7d92]">
                Reasoning · defensibility
              </p>
              <p className="truncate text-sm font-semibold text-[#0f1020]">
                "{question}"
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg border border-[#e3e5ee] bg-white px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.18em] text-[#5a5c70] transition hover:border-[#8243EA]/40 hover:text-[#5b21b6]"
          >
            Close
          </button>
        </div>

        {/* Pipeline stepper + KPI cards */}
        <div className="relative border-b border-[#e3e5ee] bg-white/70 px-6 py-5">
          <PipelineStepper stages={trace?.stages ?? null} />

          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard
              label="Verdict"
              value={trace?.verdict ?? (response.success ? 'Verified' : 'Needs review')}
              tone={trace?.verdict_tone ?? (response.success ? 'emerald' : 'amber')}
            />
            <StatCard
              label="Latency"
              value={`${trace?.latency_ms ?? response.execution_time_ms} ms`}
            />
            <StatCard
              label="Cells"
              value={String(trace?.cells_referenced ?? response.evidence_refs?.length ?? 0)}
            />
            <StatCard
              label="Steps"
              value={String(trace?.steps ?? response.iterations ?? 0)}
            />
          </div>

          {trace?.inherited_entity && trace.active_entity && (
            <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-[#8243EA]/30 bg-[#8243EA]/10 px-3 py-1 text-[11px] font-semibold text-[#5b21b6]">
              <span
                className="inline-block h-1.5 w-1.5 rounded-full bg-[#8243EA]"
                aria-hidden
              />
              Context carried forward: <code className="font-mono">{trace.active_entity}</code>
            </div>
          )}
        </div>

        {/* Tab row */}
        <div className="relative flex flex-none items-center gap-1 border-b border-[#e3e5ee] bg-white/60 px-4 py-2">
          <TabButton active={tab === 'details'} onClick={() => setTab('details')}>
            View details
          </TabButton>
          <TabButton active={tab === 'howItWorks'} onClick={() => setTab('howItWorks')}>
            How it works
          </TabButton>
        </div>

        {/* Content */}
        <div className="relative flex-1 overflow-auto bg-white/50 px-6 py-5">
          {tab === 'details' ? (
            <DetailsTab content={detailed} />
          ) : (
            <HowItWorksTab trace={trace} />
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}

// ---------------------------------------------------------------------------
// Pipeline stepper
// ---------------------------------------------------------------------------

function PipelineStepper({ stages }: { stages: ReasoningStageState[] | null }) {
  // Render the canonical 5-stage layout even when `stages` is null (e.g. a
  // reloaded conversation without a trace). Lets the modal graphic stay
  // stable across every answer.
  const fallback: Array<Pick<ReasoningStageState, 'id' | 'symbol' | 'label'>> = [
    { id: 'understand', symbol: 'U', label: 'Understand' },
    { id: 'locate', symbol: 'L', label: 'Locate' },
    { id: 'compute', symbol: 'C', label: 'Compute' },
    { id: 'simulate', symbol: 'S', label: 'Simulate' },
    { id: 'verify', symbol: 'V', label: 'Verify' },
  ];
  const effective: ReasoningStageState[] =
    stages && stages.length > 0
      ? stages
      : fallback.map((s) => ({
          ...s,
          role: '',
          status: 'skipped',
          tool_count: 0,
          total_ms: 0,
        }));

  return (
    <div className="grid grid-cols-5 items-start">
      {effective.map((stage, index) => {
        const isOk = stage.status === 'ok';
        const isFailed = stage.status === 'failed';
        const connectorFilled = isOk || isFailed;
        const nodeClass = isFailed
          ? 'bg-amber-500 text-white shadow-[0_8px_20px_rgba(245,158,11,0.3)]'
          : isOk
          ? 'bg-emerald-500 text-white shadow-[0_8px_20px_rgba(16,185,129,0.3)]'
          : 'bg-white text-[#cfd1de] border-2 border-dashed border-[#dadcea]';
        const labelClass = isOk || isFailed ? 'text-[#0f1020]' : 'text-[#9ea0b3]';
        return (
          <div key={stage.id} className="relative flex flex-col items-center">
            {index < effective.length - 1 && (
              <div className="absolute left-1/2 top-6 z-0 h-1 w-full -translate-y-1/2 overflow-hidden rounded-full bg-[#e7e9f1]">
                <div
                  className={`h-full transition-all duration-500 ${
                    connectorFilled
                      ? isFailed
                        ? 'w-full bg-amber-500'
                        : 'w-full bg-emerald-500'
                      : 'w-0'
                  }`}
                />
              </div>
            )}
            <div
              className={`relative z-10 flex h-12 w-12 items-center justify-center rounded-2xl text-lg font-bold ${nodeClass}`}
              title={stage.role || stage.label}
            >
              {isOk ? '✓' : isFailed ? '!' : stage.symbol}
            </div>
            <p className={`mt-2 text-[10px] font-bold uppercase tracking-[0.18em] ${labelClass}`}>
              {stage.label}
            </p>
            {stage.tool_count > 0 && (
              <p className="mt-0.5 font-mono text-[9px] text-[#7a7d92]">
                {stage.tool_count} · {stage.total_ms}ms
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  const toneClass =
    tone === 'emerald'
      ? 'text-emerald-700'
      : tone === 'amber'
      ? 'text-amber-700'
      : tone === 'red'
      ? 'text-red-700'
      : 'text-[#0f1020]';
  return (
    <div className="rounded-xl border border-[#e3e5ee] bg-white px-3.5 py-2.5">
      <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-[#7a7d92]">{label}</p>
      <p className={`mt-1 font-mono text-base font-bold ${toneClass}`}>{value}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab button
// ---------------------------------------------------------------------------

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-md px-3 py-1.5 text-[11px] font-bold uppercase tracking-[0.18em] transition ${
        active
          ? 'bg-[#8243EA]/10 text-[#5b21b6]'
          : 'text-[#7a7d92] hover:text-[#0f1020]'
      }`}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Details tab — full verbose answer
// ---------------------------------------------------------------------------

function DetailsTab({ content }: { content: string }) {
  if (!content) {
    return (
      <p className="text-sm text-[#7a7d92]">
        No detailed answer was captured for this response.
      </p>
    );
  }
  return (
    <div className="rounded-xl border border-[#e3e5ee] bg-white px-4 py-4">
      <AnswerMarkdown content={content} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// How it works tab — numbered narrative
// ---------------------------------------------------------------------------

function HowItWorksTab({ trace }: { trace: ReasoningTrace | null }) {
  if (!trace || !trace.narrative || trace.narrative.length === 0) {
    return (
      <p className="text-sm text-[#7a7d92]">
        No narrative was captured for this response. Try asking the question again — newer
        answers carry a full reasoning trace.
      </p>
    );
  }
  return (
    <ol className="space-y-5">
      {trace.narrative.map((step, idx) => (
        <li key={`${step.title}-${idx}`} className="relative pl-11">
          <span className="absolute left-0 top-0 flex h-8 w-8 items-center justify-center rounded-full bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-xs font-bold text-white shadow-[0_6px_16px_rgba(130,67,234,0.3)]">
            {idx + 1}
          </span>
          <p className="text-[11px] font-bold uppercase tracking-[0.22em] text-[#5b21b6]">
            {step.title}
          </p>
          <p className="mt-1 whitespace-pre-wrap text-[14px] leading-7 text-[#1f2037]">
            {step.body}
          </p>
        </li>
      ))}
    </ol>
  );
}
