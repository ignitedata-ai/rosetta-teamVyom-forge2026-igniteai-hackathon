import type { ExcelSchemaResponse } from '../api/excelAgent';

// =============================================================================
// SchemaInspector
// -----------------------------------------------------------------------------
// A modal that renders a light-themed ER-diagram of the workbook's tables and
// their relationships. Self-contained: pure data-derivation + SVG rendering
// (no extra dependencies, no global styles).
//
// Relationship source priority:
//   1. Backend `enrichment.cross_sheet_relationships` (LLM-derived) — preferred
//   2. Client-side column-name overlap inference — fallback
//
// Column-dot colors are driven by `column.semantic_role` returned by our
// SemanticEnricher (`identifier` / `dimension` / `metric` / `attribute`)
// plus the `primary_key` flag on the table.
// =============================================================================

// ----- Types -----------------------------------------------------------------

interface SchemaColumn {
  name: string;
  semantic_role?: string;
  data_type?: string;
}

interface TableView {
  name: string;
  description: string;
  rowCount: number;
  primaryKey: string | null;
  columns: SchemaColumn[];
}

interface RelationshipView {
  from: string;
  to: string;
  key: string;
}

// ----- Color palettes --------------------------------------------------------

const TABLE_PALETTE = [
  { band: '#a78bfa', text: '#5b21b6', glow: 'rgba(167,139,250,0.3)' },
  { band: '#60a5fa', text: '#1e40af', glow: 'rgba(96,165,250,0.3)' },
  { band: '#34d399', text: '#047857', glow: 'rgba(52,211,153,0.3)' },
  { band: '#fbbf24', text: '#a16207', glow: 'rgba(251,191,36,0.3)' },
  { band: '#f87171', text: '#b91c1c', glow: 'rgba(248,113,113,0.3)' },
  { band: '#2dd4bf', text: '#0f766e', glow: 'rgba(45,212,191,0.3)' },
  { band: '#f472b6', text: '#9d174d', glow: 'rgba(244,114,182,0.3)' },
];

// Dot colors per legend (PK / Dim / Metric).
const DOT_PK = '#8243EA';        // purple — primary key
const DOT_METRIC = '#10b981';    // green  — numeric measure
const DOT_DIM = '#f59e0b';       // amber  — dimension / attribute
const DOT_IDENTIFIER = '#3b82f6'; // blue   — non-PK identifier (FK candidate)
const DOT_TEMPORAL = '#0ea5e9';  // sky    — date/time

// ----- Helpers ---------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function getWorkbookTables(schema: ExcelSchemaResponse | null): TableView[] {
  if (!schema || !isRecord(schema.semantic_schema)) return [];
  const semanticTables = asArray(schema.semantic_schema.tables).filter(isRecord);

  return semanticTables.map((table) => {
    const columns = asArray(table.columns)
      .filter(isRecord)
      .map((column) => ({
        name: String(column.name ?? ''),
        semantic_role: typeof column.semantic_role === 'string' ? column.semantic_role : undefined,
        data_type: typeof column.data_type === 'string' ? column.data_type : undefined,
      }))
      .filter((c) => c.name);

    return {
      name: String(table.table_name ?? ''),
      description: String(table.description ?? ''),
      rowCount: Number(table.row_count ?? 0),
      primaryKey: typeof table.primary_key === 'string' ? table.primary_key : null,
      columns,
    };
  });
}

function getSemanticSummary(schema: ExcelSchemaResponse | null): {
  entities: string[];
  metrics: string[];
} {
  if (!schema || !isRecord(schema.enrichment)) return { entities: [], metrics: [] };
  const sm = isRecord(schema.enrichment.semantic_model) ? schema.enrichment.semantic_model : {};
  return {
    entities: asArray(sm.entities).map(String),
    metrics: asArray(sm.metrics).map(String),
  };
}

/**
 * Try to read backend-provided `enrichment.cross_sheet_relationships`.
 * Returns an empty array if absent or malformed; the caller falls back to
 * client-side inference in that case.
 */
function getBackendRelationships(schema: ExcelSchemaResponse | null): RelationshipView[] {
  if (!schema || !isRecord(schema.enrichment)) return [];
  const raw = asArray(schema.enrichment.cross_sheet_relationships).filter(isRecord);
  const out: RelationshipView[] = [];
  for (const r of raw) {
    // Accept multiple shapes from the enricher / hand-authored payloads.
    const from = String(r.from_table ?? r.from ?? r.source ?? '');
    const to = String(r.to_table ?? r.to ?? r.target ?? '');
    const key = String(r.join_key ?? r.key ?? r.column ?? r.on ?? '');
    if (from && to && key && from !== to) out.push({ from, to, key });
  }
  return out;
}

/**
 * Fallback: infer relationships from shared column names. Mirrors the 3001
 * heuristic so the diagram still works when the backend hasn't populated
 * `cross_sheet_relationships`.
 */
function inferRelationships(tables: TableView[]): RelationshipView[] {
  const ignored = new Set(['month', 'date', 'notes', 'type', 'name']);
  const relationships: RelationshipView[] = [];

  for (let i = 0; i < tables.length; i += 1) {
    for (let j = i + 1; j < tables.length; j += 1) {
      const left = tables[i];
      const right = tables[j];
      const leftNames = left.columns.map((c) => c.name);
      const rightLowered = new Set(right.columns.map((c) => c.name.trim().toLowerCase()));
      const shared = leftNames.find((column) => {
        const normalized = column.trim().toLowerCase();
        return rightLowered.has(normalized) && !ignored.has(normalized);
      });
      if (shared) {
        relationships.push({ from: left.name, to: right.name, key: shared });
      }
    }
  }
  return relationships.slice(0, 8);
}

/**
 * Public selector: prefer backend relationships, fall back to inference.
 */
function getRelationships(
  schema: ExcelSchemaResponse | null,
  tables: TableView[],
): RelationshipView[] {
  const backend = getBackendRelationships(schema);
  if (backend.length > 0) return backend.slice(0, 12);
  return inferRelationships(tables);
}

/** Map a column to a legend dot color based on its semantic role. */
function dotColorFor(column: SchemaColumn, isPk: boolean): string {
  if (isPk) return DOT_PK;
  switch ((column.semantic_role || '').toLowerCase()) {
    case 'metric':
    case 'measure':
      return DOT_METRIC;
    case 'identifier':
      return DOT_IDENTIFIER;
    case 'temporal':
    case 'date':
    case 'time':
      return DOT_TEMPORAL;
    case 'dimension':
    case 'attribute':
      return DOT_DIM;
    default:
      // Final-resort heuristic so untyped columns still get sensible colors.
      return /[$#]|rev|cost|price|total|amount|sale|gross|margin/i.test(column.name)
        ? DOT_METRIC
        : DOT_DIM;
  }
}

// ----- ERDiagram (SVG) -------------------------------------------------------

interface TablePositioned extends TableView {
  x: number;
  y: number;
  width: number;
  height: number;
  paletteIndex: number;
}

function ERDiagram({
  tables,
  relationships,
}: {
  tables: TableView[];
  relationships: RelationshipView[];
}) {
  const MAX_COLUMNS = 7;
  const CARD_WIDTH = 260;
  const ROW_HEIGHT = 22;
  const HEADER_HEIGHT = 64;
  const CELL_PADDING_X = 56;
  const CELL_PADDING_Y = 44;
  const cols = Math.min(3, Math.max(1, tables.length));
  const rows = Math.ceil(tables.length / cols);

  const positioned: TablePositioned[] = tables.map((table, index) => {
    const col = index % cols;
    const row = Math.floor(index / cols);
    const visibleColCount = Math.min(table.columns.length, MAX_COLUMNS);
    const height = HEADER_HEIGHT + visibleColCount * ROW_HEIGHT + (table.columns.length > MAX_COLUMNS ? ROW_HEIGHT : 0);
    const cardCellWidth = CARD_WIDTH + CELL_PADDING_X;
    const cardCellHeight = HEADER_HEIGHT + MAX_COLUMNS * ROW_HEIGHT + ROW_HEIGHT + CELL_PADDING_Y;
    return {
      ...table,
      x: col * cardCellWidth + CELL_PADDING_X / 2,
      y: row * cardCellHeight + CELL_PADDING_Y / 2,
      width: CARD_WIDTH,
      height,
      paletteIndex: index % TABLE_PALETTE.length,
    };
  });

  const byName = new Map(positioned.map((table) => [table.name, table]));
  const viewBoxWidth = cols * (CARD_WIDTH + CELL_PADDING_X);
  const viewBoxHeight = rows * (HEADER_HEIGHT + MAX_COLUMNS * ROW_HEIGHT + ROW_HEIGHT + CELL_PADDING_Y);

  const edges = relationships.flatMap((relationship) => {
    const from = byName.get(relationship.from);
    const to = byName.get(relationship.to);
    if (!from || !to) return [];
    const fromCx = from.x + from.width / 2;
    const toCx = to.x + to.width / 2;
    const fromRightSide = toCx > fromCx;
    const fromX = fromRightSide ? from.x + from.width : from.x;
    const toX = fromRightSide ? to.x : to.x + to.width;
    const fromY = from.y + HEADER_HEIGHT / 2;
    const toY = to.y + HEADER_HEIGHT / 2;
    const midX = (fromX + toX) / 2;
    const path = `M ${fromX} ${fromY} C ${midX} ${fromY}, ${midX} ${toY}, ${toX} ${toY}`;
    const labelX = (fromX + toX) / 2;
    const labelY = (fromY + toY) / 2 - 6;
    return [{
      key: `${relationship.from}-${relationship.to}-${relationship.key}`,
      path,
      labelX,
      labelY,
      label: relationship.key,
    }];
  });

  return (
    <svg
      viewBox={`0 0 ${viewBoxWidth} ${viewBoxHeight}`}
      className="block w-full"
      style={{ minHeight: '540px' }}
    >
      <defs>
        <marker id="erArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 Z" fill="#8243EA" />
        </marker>
      </defs>

      {edges.map((edge) => (
        <g key={edge.key}>
          <path
            d={edge.path}
            fill="none"
            stroke="#8243EA"
            strokeWidth="1.5"
            strokeDasharray="4 3"
            markerEnd="url(#erArrow)"
            opacity={0.75}
          />
          <g transform={`translate(${edge.labelX - 46}, ${edge.labelY - 10})`}>
            <rect rx="6" ry="6" width="92" height="20" fill="#ffffff" stroke="#e3e5ee" />
            <text x="46" y="14" textAnchor="middle" fontSize="11" fontFamily="monospace" fill="#5b21b6" fontWeight="700">
              {edge.label.length > 14 ? `${edge.label.slice(0, 13)}…` : edge.label}
            </text>
          </g>
        </g>
      ))}

      {positioned.map((table) => {
        const palette = TABLE_PALETTE[table.paletteIndex];
        const visibleCols = table.columns.slice(0, MAX_COLUMNS);
        const extraCount = Math.max(0, table.columns.length - MAX_COLUMNS);
        return (
          <g key={table.name} transform={`translate(${table.x}, ${table.y})`}>
            <rect
              x="0"
              y="0"
              width={table.width}
              height={table.height}
              rx="12"
              ry="12"
              fill="#ffffff"
              stroke={palette.band}
              strokeWidth="1.5"
              style={{ filter: `drop-shadow(0 8px 20px ${palette.glow})` }}
            />
            <rect x="0" y="0" width={table.width} height={HEADER_HEIGHT} rx="12" ry="12" fill={palette.band} />
            <rect x="0" y={HEADER_HEIGHT - 8} width={table.width} height="8" fill={palette.band} />
            <text x="16" y="26" fontSize="13" fontWeight="700" fill="#ffffff">
              {table.name.length > 24 ? `${table.name.slice(0, 23)}…` : table.name}
            </text>
            <text x="16" y="48" fontSize="11" fill="rgba(255,255,255,0.88)">
              {table.rowCount} rows · {table.columns.length} cols
            </text>
            {table.primaryKey && (
              <g transform={`translate(${table.width - 12}, 20)`}>
                <rect x="-52" y="-11" width="52" height="18" rx="4" fill="rgba(255,255,255,0.22)" />
                <text x="-26" y="2" textAnchor="middle" fontSize="10" fontFamily="monospace" fontWeight="700" fill="#ffffff">
                  PK
                </text>
              </g>
            )}

            {visibleCols.map((column, columnIndex) => {
              const y = HEADER_HEIGHT + columnIndex * ROW_HEIGHT;
              const isPk = table.primaryKey === column.name;
              const dot = dotColorFor(column, isPk);
              const textColor = isPk ? palette.text : '#1f2037';
              const fontWeight = isPk ? '700' : '500';
              return (
                <g key={column.name} transform={`translate(0, ${y})`}>
                  {columnIndex > 0 && <line x1="12" x2={table.width - 12} y1="0" y2="0" stroke="#eef0f7" />}
                  <circle cx="18" cy={ROW_HEIGHT / 2} r="3" fill={dot} />
                  <text x="32" y={ROW_HEIGHT / 2 + 4} fontSize="11.5" fill={textColor} fontWeight={fontWeight}>
                    {column.name.length > 26 ? `${column.name.slice(0, 25)}…` : column.name}
                  </text>
                </g>
              );
            })}
            {extraCount > 0 && (
              <g transform={`translate(0, ${HEADER_HEIGHT + MAX_COLUMNS * ROW_HEIGHT})`}>
                <text x="32" y={ROW_HEIGHT / 2 + 4} fontSize="11" fill="#7a7d92" fontStyle="italic">
                  + {extraCount} more column{extraCount === 1 ? '' : 's'}
                </text>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ----- Modal wrapper ---------------------------------------------------------

interface SchemaInspectorProps {
  open: boolean;
  onClose: () => void;
  schema: ExcelSchemaResponse | null;
  isLoading?: boolean;
  error?: string | null;
}

export default function SchemaInspector({
  open,
  onClose,
  schema,
  isLoading = false,
  error = null,
}: SchemaInspectorProps) {
  if (!open) return null;

  const tables = getWorkbookTables(schema);
  const relationships = getRelationships(schema, tables);
  const semanticSummary = getSemanticSummary(schema);

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="relative flex h-[92vh] w-full max-w-[1200px] flex-col overflow-hidden rounded-3xl border-2 border-[#e3e5ee] bg-[linear-gradient(180deg,#fdfcff,#f3f1fb)] text-[#0f1020] shadow-[0_40px_100px_rgba(0,0,0,0.5)]"
        onClick={(event) => event.stopPropagation()}
      >
        {/* Header */}
        <div className="relative flex items-center justify-between border-b border-[#e3e5ee] bg-white/85 px-6 py-4 backdrop-blur">
          <div className="flex items-center gap-3 min-w-0">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-[10px] font-bold uppercase text-white shadow-[0_8px_22px_rgba(130,67,234,0.45)]">
              DI
            </span>
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-[0.32em] text-[#7a7d92] font-bold">Semantic Layer</p>
              <p className="text-base font-semibold text-[#0f1020]">Workbook schema · relationships</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="hidden items-center gap-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#7a7d92] md:flex">
              <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: DOT_PK }} />PK</span>
              <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: DOT_DIM }} />Dim</span>
              <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: DOT_METRIC }} />Metric</span>
            </div>
            <button
              onClick={onClose}
              className="rounded-lg border border-[#e3e5ee] bg-white px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.18em] text-[#5a5c70] hover:border-[#8243EA]/40 hover:text-[#5b21b6] transition"
            >
              Close
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="relative flex-1 overflow-auto px-6 py-6">
          {isLoading ? (
            <p className="text-sm text-[#7a7d92]">Loading workbook schema…</p>
          ) : error ? (
            <p className="text-sm text-red-600">Failed to load schema: {error}</p>
          ) : tables.length === 0 ? (
            <p className="text-sm text-[#7a7d92]">Prepare the workbook to inspect its schema.</p>
          ) : (
            <ERDiagram tables={tables} relationships={relationships} />
          )}
        </div>

        {/* Footer */}
        <div className="relative border-t border-[#e3e5ee] bg-white/75 px-6 py-3">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[11px] text-[#5a5c70]">
            <span><span className="font-bold text-[#0f1020]">{tables.length}</span> tables</span>
            <span><span className="font-bold text-[#0f1020]">{relationships.length}</span> inferred joins</span>
            {semanticSummary.entities.length > 0 && (
              <span className="truncate">
                <span className="font-bold text-[#0f1020]">Entities:</span> {semanticSummary.entities.slice(0, 6).join(', ')}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
