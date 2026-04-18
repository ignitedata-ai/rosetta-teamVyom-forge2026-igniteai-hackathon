import { useMemo, useState, useCallback } from 'react';
import type { TraceNode } from '../api/excelAgent';

/**
 * FormulaBreakdown — a progressive, click-to-expand tree view of a cell's
 * backward dependency trace. Light-themed.
 */

interface Props {
  trace: TraceNode;
  /** Depth at which children are collapsed by default. */
  defaultExpandDepth?: number;
}

// Palette keyed by sheet name, assigned first-seen-first-colored.
const SHEET_COLORS = [
  { accent: 'border-l-[#8243EA]', dot: 'bg-[#8243EA]', text: 'text-[#5b21b6]' },
  { accent: 'border-l-emerald-500', dot: 'bg-emerald-500', text: 'text-emerald-700' },
  { accent: 'border-l-amber-500', dot: 'bg-amber-500', text: 'text-amber-700' },
  { accent: 'border-l-rose-500', dot: 'bg-rose-500', text: 'text-rose-700' },
  { accent: 'border-l-sky-500', dot: 'bg-sky-500', text: 'text-sky-700' },
  { accent: 'border-l-fuchsia-500', dot: 'bg-fuchsia-500', text: 'text-fuchsia-700' },
];

function useSheetColorMap(root: TraceNode) {
  return useMemo(() => {
    const order: string[] = [];
    const walk = (n: TraceNode) => {
      const sheet = n.ref.split('!', 1)[0];
      if (!order.includes(sheet)) order.push(sheet);
      (n.children ?? []).forEach(walk);
    };
    walk(root);
    return (sheet: string) => SHEET_COLORS[order.indexOf(sheet) % SHEET_COLORS.length] ?? SHEET_COLORS[0];
  }, [root]);
}

function formatValue(value: TraceNode['value']): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE';
  if (typeof value === 'number') {
    const n = value;
    if (Math.abs(n) >= 1000) {
      return Number.isInteger(n) ? n.toLocaleString() : n.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    if (Math.abs(n) < 1 && n !== 0) {
      return n.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
    }
    return Number.isInteger(n) ? String(n) : n.toFixed(2);
  }
  const s = String(value);
  return s.length <= 60 ? s : s.slice(0, 57) + '...';
}

export default function FormulaBreakdown({ trace, defaultExpandDepth = 2 }: Props) {
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const sheetColor = useSheetColorMap(trace);

  const toggle = useCallback((ref: string, depth: number) => {
    setOverrides((prev) => {
      const defaultExpanded = depth < defaultExpandDepth;
      const current = prev[ref] ?? defaultExpanded;
      return { ...prev, [ref]: !current };
    });
  }, [defaultExpandDepth]);

  const totalLeafs = useMemo(() => {
    let leaves = 0;
    const walk = (n: TraceNode) => {
      if (!n.children || n.children.length === 0) leaves += 1;
      else n.children.forEach(walk);
    };
    walk(trace);
    return leaves;
  }, [trace]);

  return (
    <div className="mt-3 border border-[#e3e5ee] rounded-lg bg-[#f9f8fd] overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#e3e5ee] text-xs text-[#5a5c70] flex-wrap gap-y-1">
        <div className="flex items-center gap-3">
          <span className="text-[10px] uppercase tracking-[0.18em] text-[#0f1020] font-semibold">Formula breakdown</span>
          <span className="text-[#7a7d92]">{totalLeafs} leaf inputs · click rows to expand</span>
        </div>
        <div className="flex items-center gap-2 text-[#7a7d92] text-[10px]">
          <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-amber-500" /> hardcoded</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-orange-500" /> volatile</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-[#8243EA]" /> named range</span>
        </div>
      </div>
      <div className="p-2 max-h-[460px] overflow-auto font-mono text-xs">
        <Row
          node={trace}
          depth={0}
          isLast
          sheetColor={sheetColor}
          overrides={overrides}
          toggle={toggle}
          defaultExpandDepth={defaultExpandDepth}
        />
      </div>
    </div>
  );
}

interface RowProps {
  node: TraceNode;
  depth: number;
  isLast: boolean;
  sheetColor: (sheet: string) => typeof SHEET_COLORS[0];
  overrides: Record<string, boolean>;
  toggle: (ref: string, depth: number) => void;
  defaultExpandDepth: number;
}

function Row({ node, depth, sheetColor, overrides, toggle, defaultExpandDepth }: RowProps) {
  const sheet = node.ref.split('!', 1)[0];
  const coord = node.ref.includes('!') ? node.ref.slice(sheet.length + 1) : node.ref;
  const colors = sheetColor(sheet);
  const value = formatValue(node.value);
  const hasChildren = (node.children?.length ?? 0) > 0;
  const defaultExpanded = depth < defaultExpandDepth;
  const expanded = overrides[node.ref] ?? defaultExpanded;

  return (
    <div>
      <div
        className={`group pl-2 pr-3 py-1.5 border-l-2 ${colors.accent} ${hasChildren ? 'cursor-pointer hover:bg-[#8243EA]/5' : ''} rounded-sm`}
        style={{ marginLeft: depth * 18 }}
        onClick={hasChildren ? () => toggle(node.ref, depth) : undefined}
      >
        <div className="flex items-center gap-2 flex-wrap">
          <span className="w-3 text-[#7a7d92] select-none">
            {hasChildren ? (expanded ? '▼' : '▶') : '•'}
          </span>

          <span className={`w-1.5 h-1.5 rounded-full ${colors.dot} shrink-0`} />
          <span className="text-[#5a5c70] truncate max-w-[200px]" title={node.ref}>
            <span className={colors.text}>{sheet}</span>
            <span className="text-[#9a9caf]">!</span>
            <span className="text-[#0f1020]">{coord}</span>
          </span>

          {node.label && (
            <span className="text-[#0f1020] font-semibold truncate">{node.label}</span>
          )}

          {value != null && (
            <span className="text-emerald-700 shrink-0">= {value}</span>
          )}

          <span className="flex gap-1 ml-auto shrink-0">
            {node.named_range && (
              <Badge color="indigo" title={`Named range: ${node.named_range}`}>⬩ {node.named_range}</Badge>
            )}
            {node.is_hardcoded && (
              <Badge color="amber" title="Hardcoded value — not computed from a formula">⚠ hardcoded</Badge>
            )}
            {node.is_volatile && (
              <Badge color="orange" title="Uses a volatile function (NOW / TODAY / OFFSET / INDIRECT)">⚡ volatile</Badge>
            )}
            {node.children?.length != null && node.children.length > 0 && (
              <Badge color="slate" title={`${node.children.length} direct precedent(s)`}>{node.children.length}↓</Badge>
            )}
          </span>
        </div>

        {node.formula && (
          <div className="pl-5 mt-0.5 text-[11px] text-[#5a5c70] truncate" title={`=${node.formula}`}>
            <span className="text-[#9a9caf]">=</span>
            {node.formula}
          </div>
        )}

        {node.warnings && node.warnings.length > 0 && (
          <div className="pl-5 mt-0.5 space-y-0.5">
            {node.warnings.map((w, i) => (
              <div key={i} className="text-[10px] text-amber-700">⚠ {w}</div>
            ))}
          </div>
        )}
      </div>

      {hasChildren && expanded && (
        <div>
          {node.children!.map((child, idx) => (
            <Row
              key={`${child.ref}-${idx}`}
              node={child}
              depth={depth + 1}
              isLast={idx === node.children!.length - 1}
              sheetColor={sheetColor}
              overrides={overrides}
              toggle={toggle}
              defaultExpandDepth={defaultExpandDepth}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function Badge({
  children,
  color,
  title,
}: {
  children: React.ReactNode;
  color: 'amber' | 'orange' | 'indigo' | 'slate';
  title?: string;
}) {
  const cls = {
    amber: 'bg-amber-50 text-amber-700 border-amber-200',
    orange: 'bg-orange-50 text-orange-700 border-orange-200',
    indigo: 'bg-[#8243EA]/10 text-[#5b21b6] border-[#8243EA]/30',
    slate: 'bg-white text-[#5a5c70] border-[#e3e5ee]',
  }[color];
  return (
    <span className={`px-1.5 py-0.5 rounded border text-[10px] ${cls}`} title={title}>
      {children}
    </span>
  );
}
