/**
 * FormulaModal — popup container for the formula visualisation.
 *
 * Houses two interchangeable views of the same trace payload:
 *   • Map     (default) — horizontal node-link tree of circles
 *   • Formula          — the raw formula + signed chips of direct
 *                        precedents, centered on a cream canvas
 *
 * A segmented toggle in the header switches between them; the choice is
 * persisted in localStorage so the user's preference sticks across
 * sessions.
 *
 * Dismiss: Esc key, X button, click outside the panel.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { TraceNode } from '../api/excelAgent';
import FormulaMap from './FormulaMap';
import EquationChips from './EquationChips';

type View = 'map' | 'formula';

const STORAGE_KEY = 'rosetta.formulaModal.view';

/** Coerce any legacy stored value (previously 'sunburst' or 'tree') to
 * the current view vocabulary. Unknown values fall back to the default. */
function readStoredView(): View {
  if (typeof window === 'undefined') return 'map';
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (raw === 'formula') return 'formula';
  return 'map';
}

interface Props {
  trace: TraceNode;
  open: boolean;
  onClose: () => void;
}

export default function FormulaModal({ trace, open, onClose }: Props) {
  const [view, setView] = useState<View>(() => readStoredView());
  const panelRef = useRef<HTMLDivElement | null>(null);

  // Persist toggle choice
  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, view);
    }
  }, [view]);

  // Esc to close + body scroll lock while open
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  const onBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) onClose();
    },
    [onClose]
  );

  if (!open || typeof document === 'undefined') return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[80] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onBackdropClick}
    >
      <div
        ref={panelRef}
        className="w-[92vw] h-[88vh] max-w-[1400px] bg-[#10101b] border border-slate-700 rounded-2xl shadow-2xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
          <div>
            <div className="text-sm text-slate-400">Formula visualisation</div>
            <div className="text-base font-semibold text-white truncate max-w-[60vw]">
              {trace.label || trace.ref}
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* Segmented toggle */}
            <div className="inline-flex rounded-lg bg-slate-800/60 p-0.5 border border-slate-700">
              <button
                onClick={() => setView('map')}
                className={`px-3 py-1 text-xs rounded-md transition ${
                  view === 'map'
                    ? 'bg-slate-700 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Map
              </button>
              <button
                onClick={() => setView('formula')}
                className={`px-3 py-1 text-xs rounded-md transition ${
                  view === 'formula'
                    ? 'bg-slate-700 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Formula
              </button>
            </div>
            <button
              onClick={onClose}
              aria-label="Close"
              className="w-8 h-8 rounded-md text-slate-300 hover:bg-slate-800/60 hover:text-white flex items-center justify-center"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Body — single-row fill; the active view owns the whole canvas.
            The Formula view carries its own cream background and centers
            its content to a comfortable reading width. */}
        <div className="flex-1 min-h-0 overflow-hidden">
          {view === 'map' ? (
            <FormulaMap trace={trace} />
          ) : (
            <div
              className="h-full overflow-auto"
              style={{ backgroundColor: '#faf7f2' }}
            >
              <div className="max-w-[760px] mx-auto py-10 px-6">
                <EquationChips focal={trace} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
