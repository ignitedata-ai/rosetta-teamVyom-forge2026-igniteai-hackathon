/**
 * FormulaMap — horizontal node-link tree for a formula's dependency graph.
 *
 * Root (focal cell) on the left. Children branch rightward in successive
 * columns; each child becomes the parent of its own sub-branch. Circle
 * size shrinks with depth (root biggest, leaves smallest) — matching the
 * user's "grandparent much larger, children smaller" mental model.
 *
 * Color encodes sign (green = positive contribution, red = negative,
 * blue = focal). Labels sit outside each circle so they stay readable at
 * every size. Pan + zoom + collapse/expand come from react-d3-tree; we
 * only own the node renderer and the data transform.
 *
 * The equation chips below the map give the exact textual breakdown.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Tree, { type CustomNodeElementProps, type RawNodeDatum } from 'react-d3-tree';
import type { TraceNode } from '../api/excelAgent';

// --- Data shape -------------------------------------------------------

interface NodeAttributes extends Record<string, string | number | boolean> {
  sheet: string;
  fullSheet: string;
  coord: string;
  ref: string;
  displayValue: string;
  rawValue: string; // serialized so Record<string, primitive> constraint holds
  formula: string;
  namedRange: string;
  sign: 'positive' | 'negative' | 'zero' | 'focal';
  isHardcoded: boolean;
  isVolatile: boolean;
  depth: number;
  hasChildren: boolean;
}

type MapDatum = RawNodeDatum & { attributes: NodeAttributes };

const SHEET_LABEL_MAX = 12;

function truncateSheet(name: string): string {
  return name.length > SHEET_LABEL_MAX ? `${name.slice(0, 12)}...` : name;
}

function deriveDisplayName(node: TraceNode, fallbackMax = 22): string {
  const raw = (node.label && node.label.trim()) || node.formula || node.ref || '—';
  const clean = raw.replace(/\s+/g, ' ').trim();
  return clean.length > fallbackMax ? `${clean.slice(0, fallbackMax - 1)}…` : clean;
}

function formatValue(v: TraceNode['value']): string {
  if (typeof v === 'number' && Number.isFinite(v)) {
    const abs = Math.abs(v);
    if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
    if (abs >= 1_000) return Math.round(v).toLocaleString();
    if (abs >= 1) return v.toFixed(2);
    if (abs === 0) return '0';
    return v.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
  }
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
  if (typeof v === 'string') return v.length > 18 ? v.slice(0, 17) + '…' : v;
  return '—';
}

function signOf(v: TraceNode['value'], isFocal: boolean): NodeAttributes['sign'] {
  if (isFocal) return 'focal';
  if (typeof v !== 'number') return 'zero';
  if (v > 0) return 'positive';
  if (v < 0) return 'negative';
  return 'zero';
}

function toMapDatum(node: TraceNode, depth = 0): MapDatum {
  const sheet = node.ref?.split('!', 1)[0] ?? '';
  const coord = node.ref?.includes('!') ? node.ref.split('!').slice(1).join('!') : node.ref ?? '';
  const children = (node.children ?? []).map((c) => toMapDatum(c, depth + 1));
  return {
    name: deriveDisplayName(node),
    attributes: {
      sheet: truncateSheet(sheet),
      fullSheet: sheet,
      coord,
      ref: node.ref ?? '',
      displayValue: formatValue(node.value),
      rawValue: typeof node.value === 'number' ? String(node.value) : '',
      formula: node.formula ?? '',
      namedRange: node.named_range ?? '',
      sign: signOf(node.value, depth === 0),
      isHardcoded: !!node.is_hardcoded,
      isVolatile: !!node.is_volatile,
      depth,
      hasChildren: children.length > 0,
    },
    children: children.length ? children : undefined,
  };
}

// --- Visual spec ------------------------------------------------------

// Rounded-rectangle node sizes by depth. Width shrinks with depth so the
// parent→child hierarchy is visible at a glance, but HEIGHT is held
// constant at 94px across all levels — the three content lines (name,
// value, sheet) plus padding need ~60px, and forcing depth-3+ boxes to
// be shorter was clipping the text at those levels.
const SIZE_BY_DEPTH: Array<{ w: number; h: number }> = [
  { w: 228, h: 94 }, // depth 0 — focal
  { w: 212, h: 94 }, // depth 1
  { w: 196, h: 94 }, // depth 2
  { w: 180, h: 94 }, // depth 3
  { w: 168, h: 94 }, // depth 4+
];

function sizeFor(depth: number): { w: number; h: number } {
  return SIZE_BY_DEPTH[Math.min(depth, SIZE_BY_DEPTH.length - 1)];
}

// Soft, high-contrast palette on a cream background. Each sign gets a
// pastel fill, a slightly darker border for edge definition, and a deep
// text colour so the metric name reads clearly without needing bold.
const COLOR_BY_SIGN: Record<
  NodeAttributes['sign'],
  { fill: string; stroke: string; text: string; meta: string }
> = {
  focal:    { fill: '#dbeafe', stroke: '#3b82f6', text: '#1e3a8a', meta: '#475569' }, // blue family
  positive: { fill: '#dcfce7', stroke: '#16a34a', text: '#14532d', meta: '#475569' }, // emerald family
  negative: { fill: '#fee2e2', stroke: '#dc2626', text: '#7f1d1d', meta: '#475569' }, // red family
  zero:     { fill: '#f1f5f9', stroke: '#94a3b8', text: '#334155', meta: '#64748b' }, // slate family
};

// Canvas background — warm off-white. Creates contrast with the modal's
// dark chrome and makes the colourful nodes sit comfortably without glare.
const CANVAS_BG = '#faf7f2';

// --- Node renderer ----------------------------------------------------

// Font stack — matches what Tailwind's `font-sans` resolves to in the rest
// of the UI (same family as the Map/Tree toggle buttons). Inter is loaded
// from Google Fonts via a <link> injected into <head> below; until it
// loads, the platform UI font is used. Every node uses weight 400.
const FONT_STACK =
  '"Inter", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
const MONO_STACK =
  '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace';

/** Inject the Google Fonts stylesheet into <head> once per page. This is
 * more reliable than `@import` inside an SVG-scoped style — browsers
 * lazy-load @import and sometimes skip applying it to SVG text. A real
 * <link> in head is fetched eagerly and applies everywhere. */
let fontsInjected = false;
function ensureFontsLoaded(): void {
  if (fontsInjected || typeof document === 'undefined') return;
  fontsInjected = true;
  // Preconnect for faster font fetch
  const pre1 = document.createElement('link');
  pre1.rel = 'preconnect';
  pre1.href = 'https://fonts.googleapis.com';
  const pre2 = document.createElement('link');
  pre2.rel = 'preconnect';
  pre2.href = 'https://fonts.gstatic.com';
  pre2.crossOrigin = 'anonymous';
  // The font itself — regular + a slightly heavier option we don't end up
  // using but is cheap to fetch together; mono for the value line.
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href =
    'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500&family=JetBrains+Mono:wght@400&display=swap';
  document.head.appendChild(pre1);
  document.head.appendChild(pre2);
  document.head.appendChild(link);
}

function renderNode({ nodeDatum, toggleNode, hierarchyPointNode }: CustomNodeElementProps) {
  const attrs = (nodeDatum.attributes ?? {}) as NodeAttributes;
  const depth = hierarchyPointNode?.depth ?? attrs.depth ?? 0;
  const { w, h } = sizeFor(depth);
  const palette = COLOR_BY_SIGN[attrs.sign] ?? COLOR_BY_SIGN.zero;
  const collapsed = !!(nodeDatum as RawNodeDatum & { __rd3t?: { collapsed?: boolean } }).__rd3t?.collapsed;
  const descendantCount = hierarchyPointNode?.descendants ? hierarchyPointNode.descendants().length - 1 : 0;

  // Character budgets scale with width so labels rarely clip.
  const nameBudget = depth === 0 ? 24 : depth === 1 ? 22 : depth === 2 ? 20 : 18;
  const name =
    nodeDatum.name.length > nameBudget ? `${nodeDatum.name.slice(0, nameBudget - 1)}…` : nodeDatum.name;
  const sheetLine = attrs.sheet && attrs.coord ? `${attrs.sheet} · ${attrs.coord}` : attrs.sheet || attrs.coord;

  // We render the visible node's BACKGROUND (shadow + border) as SVG <rect>s
  // because shadows and stroked borders are easy there. All TEXT is placed
  // inside a <foreignObject> rendering HTML — SVG text has unreliable font
  // loading and browsers often fail to apply custom fonts / weights to
  // <text> elements. HTML inside foreignObject uses the document's CSS
  // engine exactly like any other div, so Inter + font-weight 400 behave
  // identically to the rest of the UI (e.g. the Map/Tree toggle buttons).
  return (
    <g style={{ cursor: attrs.hasChildren ? 'pointer' : 'default' }} onClick={toggleNode}>
      {/* Subtle drop shadow */}
      <rect
        x={-w / 2 + 1}
        y={-h / 2 + 2}
        rx={12}
        ry={12}
        width={w}
        height={h}
        fill="rgba(15, 23, 42, 0.08)"
      />
      {/* Collapsed-subtree halo */}
      {collapsed && attrs.hasChildren && (
        <rect
          x={-w / 2 - 4}
          y={-h / 2 - 4}
          rx={14}
          ry={14}
          width={w + 8}
          height={h + 8}
          fill="none"
          stroke={palette.stroke}
          strokeWidth={1.2}
          strokeDasharray="3 4"
          opacity={0.7}
        />
      )}
      {/* Main rect */}
      <rect
        x={-w / 2}
        y={-h / 2}
        rx={12}
        ry={12}
        width={w}
        height={h}
        fill={palette.fill}
        stroke={palette.stroke}
        strokeWidth={1.4}
      />

      {/* All text inside a foreignObject => HTML => real CSS / real fonts. */}
      <foreignObject
        x={-w / 2}
        y={-h / 2}
        width={w}
        height={h}
        style={{ pointerEvents: 'none' }}
      >
        <div
          // `xmlns` is a valid attribute on HTML content inside an SVG
          // <foreignObject> but not part of React's HTMLDivElement types.
          // Spread-cast keeps the runtime attribute without widening the
          // div props type.
          {...({ xmlns: 'http://www.w3.org/1999/xhtml' } as Record<string, string>)}
          style={{
            width: '100%',
            height: '100%',
            boxSizing: 'border-box',
            padding: '10px 14px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center',
            fontFamily: FONT_STACK,
            color: palette.text,
            lineHeight: 1.3,
            userSelect: 'none',
          }}
        >
          {/* Metric name — light weight, clear color */}
          <div
            style={{
              fontSize: depth === 0 ? 15 : 14,
              fontWeight: 400,
              letterSpacing: '-0.01em',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              maxWidth: '100%',
            }}
            title={nodeDatum.name}
          >
            {name}
          </div>

          {/* Value — monospace, slightly smaller */}
          {attrs.displayValue && attrs.displayValue !== '—' && (
            <div
              style={{
                fontFamily: MONO_STACK,
                fontSize: 13,
                fontWeight: 400,
                marginTop: 4,
                color: palette.text,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {attrs.displayValue}
            </div>
          )}

          {/* Sheet · coord — meta line, muted */}
          {sheetLine && (
            <div
              style={{
                fontSize: 11,
                fontWeight: 400,
                marginTop: 4,
                color: palette.meta,
                letterSpacing: '0.01em',
              }}
              title={`${attrs.fullSheet}!${attrs.coord}`}
            >
              {sheetLine}
            </div>
          )}

          {/* Warning markers at bottom-left corner */}
          {(attrs.isHardcoded || attrs.isVolatile) && (
            <div
              style={{
                position: 'absolute',
                left: 8,
                bottom: 6,
                fontSize: 11,
                color: palette.meta,
                display: 'flex',
                gap: 4,
              }}
            >
              {attrs.isHardcoded && <span title="hardcoded value">⚠</span>}
              {attrs.isVolatile && <span title="volatile function">⚡</span>}
            </div>
          )}
        </div>
      </foreignObject>

      {/* Collapsed count badge stays SVG for easy positioning on the rect corner */}
      {collapsed && descendantCount > 0 && (
        <g transform={`translate(${w / 2 - 18}, ${-h / 2 + 12})`}>
          <rect x={-12} y={-10} rx={9} ry={9} width={32} height={18} fill={palette.stroke} />
          <foreignObject x={-12} y={-10} width={32} height={18} style={{ pointerEvents: 'none' }}>
            <div
              // See note above — xmlns on HTML inside <foreignObject> is
              // a valid runtime attribute, passed via spread-cast so the
              // TS HTMLDivElement type isn't polluted.
              {...({ xmlns: 'http://www.w3.org/1999/xhtml' } as Record<string, string>)}
              style={{
                width: '100%',
                height: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontFamily: MONO_STACK,
                fontSize: 10,
                fontWeight: 400,
                color: '#ffffff',
                userSelect: 'none',
              }}
            >
              +{descendantCount}
            </div>
          </foreignObject>
        </g>
      )}
    </g>
  );
}

// --- Component --------------------------------------------------------

interface Props {
  trace: TraceNode;
  /** Called when the user clicks a node — reserved for future focus/re-root. */
  onNodeFocus?: (datum: MapDatum) => void;
}

export default function FormulaMap({ trace }: Props) {
  const data = useMemo(() => toMapDatum(trace), [trace]);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [translate, setTranslate] = useState<{ x: number; y: number }>({ x: 120, y: 200 });

  // Inject the Google Fonts <link> into <head> on first mount as a
  // safety net — the primary load happens from index.html. This second
  // injection is a no-op on most runs thanks to the module-level guard.
  useEffect(() => {
    ensureFontsLoaded();
  }, []);

  // Center the tree vertically in the container on mount / container resize.
  // react-d3-tree's `translate` positions the root; we offset it left so
  // the horizontal tree has room to grow rightward.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      const { width, height } = el.getBoundingClientRect();
      setTranslate({ x: Math.max(100, width * 0.15), y: height / 2 });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const renderCustomNodeElement = useCallback((props: CustomNodeElementProps) => renderNode(props), []);

  return (
    <div ref={containerRef} className="h-full w-full relative" style={{ backgroundColor: CANVAS_BG }}>
      <Tree
        data={data}
        orientation="horizontal"
        pathFunc="diagonal"
        translate={translate}
        nodeSize={{ x: 300, y: 130 }}
        separation={{ siblings: 1.05, nonSiblings: 1.3 }}
        zoomable
        draggable
        collapsible
        initialDepth={1}
        renderCustomNodeElement={renderCustomNodeElement}
        pathClassFunc={() => 'rd3t-link-custom'}
      />
      {/* Stroke colour for the tree's edges, soft slate on cream.
          Font control is handled in-HTML (via foreignObject) rather than
          in-SVG, so no font rules are needed here. */}
      <style>{`
        .rd3t-link-custom { stroke: #cbd5e1; stroke-width: 1.6; fill: none; }
        .rd3t-tree-container { background: transparent; }
      `}</style>
      {/* Legend — sits on the cream canvas, so uses dark readable text */}
      <div
        className="absolute bottom-3 left-4 flex items-center gap-4 text-xs"
        style={{ color: '#475569', fontFamily: FONT_STACK }}
      >
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block w-3 h-3 rounded"
            style={{ background: COLOR_BY_SIGN.focal.fill, border: `1.4px solid ${COLOR_BY_SIGN.focal.stroke}` }}
          />
          focal
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block w-3 h-3 rounded"
            style={{ background: COLOR_BY_SIGN.positive.fill, border: `1.4px solid ${COLOR_BY_SIGN.positive.stroke}` }}
          />
          positive
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block w-3 h-3 rounded"
            style={{ background: COLOR_BY_SIGN.negative.fill, border: `1.4px solid ${COLOR_BY_SIGN.negative.stroke}` }}
          />
          negative
        </span>
        <span className="ml-2 text-[11px]" style={{ color: '#64748b' }}>
          click a node to expand / collapse · drag to pan · scroll to zoom
        </span>
      </div>
    </div>
  );
}
