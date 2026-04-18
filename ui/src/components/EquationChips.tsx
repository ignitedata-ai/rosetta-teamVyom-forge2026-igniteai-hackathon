/**
 * EquationChips — textual formula breakdown presented as signed chips.
 *
 * Shown in the Formula view of the modal: centered on a cream canvas,
 * matching the Map view's visual language. Each chip corresponds to one
 * direct precedent of the focal cell and carries:
 *
 *   [ sign ]  metric label        value          sheet!coord     · named range
 *
 * Signs are derived from the focal cell's formula string: a child that
 * appears after a `-` operator is subtracted; `*` / `/` → multiplicative.
 * First operand has no leading operator so defaults to `+`.
 */

import type { TraceNode } from '../api/excelAgent';

type Sign = '+' | '-' | '·';

const FONT_STACK =
  '"Inter", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
const MONO_STACK =
  '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace';

// Palette parallels the Map's sign colors but tuned for chip density —
// softer pastel backgrounds, deeper text for legibility on cream.
const SIGN_STYLE: Record<
  Sign,
  { bg: string; borderAccent: string; text: string; accent: string; symbol: string }
> = {
  '+': { bg: '#ecfdf5', borderAccent: '#059669', text: '#064e3b', accent: '#059669', symbol: '+' },
  '-': { bg: '#fef2f2', borderAccent: '#dc2626', text: '#7f1d1d', accent: '#dc2626', symbol: '−' },
  '·': { bg: '#eef2ff', borderAccent: '#6366f1', text: '#312e81', accent: '#6366f1', symbol: '×' },
};

/** Scan the focal cell's formula for an operator immediately preceding
 * this child's coord. Works for the common flat arithmetic case
 * `=G18-G25+B15`. Falls back to `+` if ambiguous. */
function deriveSign(formula: string | null | undefined, childRef: string | undefined): Sign {
  if (!formula || !childRef) return '+';
  const coord = childRef.includes('!') ? childRef.split('!').slice(1).join('!') : childRef;
  const escaped = coord.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(
    `([+\\-*/])\\s*(?:'[^']+'!|[A-Za-z_][\\w]*!)?\\$?${escaped}\\b`
  );
  const m = re.exec(formula);
  if (!m) return '+';
  const op = m[1];
  if (op === '-') return '-';
  if (op === '*' || op === '/') return '·';
  return '+';
}

function formatValue(v: TraceNode['value']): string {
  if (typeof v === 'number' && Number.isFinite(v)) {
    const abs = Math.abs(v);
    if (abs >= 1_000)
      return v.toLocaleString(undefined, {
        maximumFractionDigits: 2,
      });
    if (abs >= 1) return v.toFixed(2);
    if (abs === 0) return '0';
    return v.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
  }
  if (typeof v === 'string') return v;
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
  return '—';
}

interface Props {
  focal: TraceNode;
}

export default function EquationChips({ focal }: Props) {
  const children = focal.children ?? [];

  // Empty / terminal state — show a friendly note rather than nothing.
  if (!children.length) {
    return (
      <div
        style={{ fontFamily: FONT_STACK, color: '#475569', fontWeight: 400 }}
        className="text-center py-10 text-sm"
      >
        This cell has no dependencies — it's a terminal value.
      </div>
    );
  }

  const sheet = focal.ref?.split('!', 1)[0] ?? '';
  const coord = focal.ref?.includes('!') ? focal.ref.split('!').slice(1).join('!') : focal.ref;

  return (
    <div style={{ fontFamily: FONT_STACK, color: '#0f172a', fontWeight: 400 }}>
      {/* Focal header */}
      <div className="mb-5 pb-4 border-b" style={{ borderColor: '#e2e8f0' }}>
        <div style={{ fontSize: 22, fontWeight: 400, letterSpacing: '-0.01em', color: '#0f172a' }}>
          {focal.label || focal.ref}
        </div>
        <div
          className="mt-1.5 flex items-center gap-2 flex-wrap"
          style={{ fontSize: 12, color: '#64748b' }}
        >
          {sheet && coord && (
            <span style={{ fontFamily: MONO_STACK }}>
              {sheet} · {coord}
            </span>
          )}
          {typeof focal.value === 'number' && (
            <>
              <span style={{ color: '#cbd5e1' }}>·</span>
              <span
                style={{
                  fontFamily: MONO_STACK,
                  color: '#0f172a',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {formatValue(focal.value)}
              </span>
            </>
          )}
        </div>
      </div>

      {/* Raw formula text */}
      {focal.formula && (
        <div
          className="mb-6 px-3 py-2 rounded-md overflow-x-auto"
          style={{
            fontFamily: MONO_STACK,
            fontSize: 13,
            fontWeight: 400,
            backgroundColor: '#f1f5f9',
            color: '#334155',
            lineHeight: 1.5,
          }}
        >
          <span style={{ color: '#94a3b8' }}>=</span> {focal.formula}
        </div>
      )}

      {/* Signed chips */}
      <div className="flex flex-col gap-2">
        {children.map((child, idx) => {
          const sign: Sign = idx === 0 ? '+' : deriveSign(focal.formula, child.ref);
          const style = SIGN_STYLE[sign];
          const childSheet = child.ref?.split('!', 1)[0] ?? '';
          const childCoord = child.ref?.includes('!')
            ? child.ref.split('!').slice(1).join('!')
            : child.ref ?? '';

          return (
            <div
              key={`${child.ref}-${idx}`}
              className="flex items-center gap-3 px-4 py-3 rounded-lg"
              style={{
                backgroundColor: style.bg,
                borderLeft: `3px solid ${style.borderAccent}`,
              }}
            >
              {/* Sign — prominent, first operand is blank */}
              <div
                style={{
                  color: style.accent,
                  fontSize: 18,
                  fontWeight: 400,
                  fontFamily: MONO_STACK,
                  width: 20,
                  textAlign: 'center',
                  flexShrink: 0,
                }}
              >
                {idx === 0 ? '' : style.symbol}
              </div>

              {/* Metric label */}
              <div
                className="flex-1 min-w-0 truncate"
                style={{ color: style.text, fontSize: 14, fontWeight: 400 }}
                title={child.label || child.ref || undefined}
              >
                {child.label || child.ref || '—'}
              </div>

              {/* Value */}
              <div
                className="shrink-0 text-right"
                style={{
                  color: style.text,
                  fontSize: 14,
                  fontFamily: MONO_STACK,
                  fontVariantNumeric: 'tabular-nums',
                  minWidth: 90,
                }}
              >
                {formatValue(child.value)}
              </div>

              {/* Sheet · coord */}
              {(childSheet || childCoord) && (
                <div
                  className="shrink-0"
                  style={{
                    color: '#64748b',
                    fontSize: 12,
                    fontFamily: MONO_STACK,
                    minWidth: 140,
                    textAlign: 'right',
                  }}
                >
                  {childSheet}
                  {childSheet && childCoord && ' · '}
                  {childCoord}
                </div>
              )}

              {/* Named range */}
              {child.named_range && (
                <div
                  className="shrink-0"
                  style={{
                    color: '#6366f1',
                    fontSize: 12,
                    fontFamily: MONO_STACK,
                  }}
                  title={`Named range: ${child.named_range}`}
                >
                  · {child.named_range}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
