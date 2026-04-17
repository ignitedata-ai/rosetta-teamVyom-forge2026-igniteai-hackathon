import { useMemo, useState, useCallback } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from 'dagre';
import type { DependencyGraphData, DependencyGraphNodeData } from '../api/excelAgent';

// --- Node sizing ---
// Fixed width so dagre can lay cells out neatly; height is loose since nodes
// vary with formula length.
const NODE_WIDTH = 220;
const NODE_HEIGHT = 96;

// --- Colors per sheet (cycle through a small palette) ---
const SHEET_PALETTE = [
  { bg: 'bg-indigo-950/60', border: 'border-indigo-400', dot: 'bg-indigo-400' },
  { bg: 'bg-emerald-950/60', border: 'border-emerald-400', dot: 'bg-emerald-400' },
  { bg: 'bg-amber-950/60', border: 'border-amber-400', dot: 'bg-amber-400' },
  { bg: 'bg-rose-950/60', border: 'border-rose-400', dot: 'bg-rose-400' },
  { bg: 'bg-sky-950/60', border: 'border-sky-400', dot: 'bg-sky-400' },
  { bg: 'bg-purple-950/60', border: 'border-purple-400', dot: 'bg-purple-400' },
];

function sheetColor(sheet: string, sheetOrder: string[]) {
  const idx = sheetOrder.indexOf(sheet);
  return SHEET_PALETTE[(idx >= 0 ? idx : 0) % SHEET_PALETTE.length];
}

// --- Custom node component ---
function CellNode({ data }: NodeProps<Node<DependencyGraphNodeData & { palette: typeof SHEET_PALETTE[0] }>>) {
  const palette = data.palette;
  const focalRing = data.is_focal ? 'ring-2 ring-white ring-offset-1 ring-offset-slate-900' : '';
  return (
    <div
      className={`${palette.bg} ${palette.border} ${focalRing} border rounded-lg px-3 py-2 text-slate-100 shadow-md w-[220px]`}
      title={data.ref}
    >
      <Handle type="target" position={Position.Left} className="!bg-slate-400" />
      <div className="flex items-center gap-2 mb-1">
        <span className={`w-2 h-2 rounded-full ${palette.dot}`} />
        <span className="text-[10px] font-mono text-slate-400 truncate">{data.sheet}</span>
        <span className="text-[10px] font-mono text-slate-500 ml-auto">{data.coord}</span>
      </div>
      {data.label && (
        <div className="text-sm font-semibold truncate mb-0.5">{data.label}</div>
      )}
      {data.value != null && (
        <div className="text-xs text-emerald-300 font-mono truncate">{data.value}</div>
      )}
      {data.formula && (
        <div className="text-[10px] text-slate-400 font-mono truncate mt-1" title={data.formula}>
          ={data.formula}
        </div>
      )}
      {data.is_hardcoded && (
        <div className="text-[9px] text-amber-300 mt-1">⚠ hardcoded</div>
      )}
      {data.is_volatile && (
        <div className="text-[9px] text-amber-300 mt-1">⚠ volatile</div>
      )}
      {data.named_range && (
        <div className="text-[9px] text-indigo-300 mt-1">⬩ {data.named_range}</div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-slate-400" />
    </div>
  );
}

const nodeTypes = { cell: CellNode };

// --- Dagre layout ---
function layout(nodes: Node[], edges: Edge[]) {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 80, marginx: 20, marginy: 20 });

  nodes.forEach((n) => g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  return nodes.map((n) => {
    const p = g.node(n.id);
    return {
      ...n,
      position: { x: p.x - NODE_WIDTH / 2, y: p.y - NODE_HEIGHT / 2 },
      targetPosition: Position.Left,
      sourcePosition: Position.Right,
    };
  });
}

interface Props {
  graph: DependencyGraphData;
}

export default function DependencyGraphCard({ graph }: Props) {
  const [fullscreen, setFullscreen] = useState(false);

  // Stable sheet order so colors are consistent across renders.
  const sheetOrder = useMemo(() => {
    const seen: string[] = [];
    for (const n of graph.nodes) {
      if (!seen.includes(n.data.sheet)) seen.push(n.data.sheet);
    }
    return seen;
  }, [graph.nodes]);

  const { rfNodes, rfEdges } = useMemo(() => {
    const rawNodes: Node[] = graph.nodes.map((n) => ({
      id: n.id,
      type: 'cell',
      position: { x: 0, y: 0 },
      data: { ...n.data, palette: sheetColor(n.data.sheet, sheetOrder) },
    }));
    const rawEdges: Edge[] = graph.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      animated: false,
      style: { stroke: '#94a3b8', strokeWidth: 1.5 },
    }));
    return { rfNodes: layout(rawNodes, rawEdges), rfEdges: rawEdges };
  }, [graph, sheetOrder]);

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    const data = node.data as DependencyGraphNodeData;
    console.log('Cell:', data.ref, data);
  }, []);

  const containerClass = fullscreen
    ? 'fixed inset-4 z-50 bg-slate-950 border border-slate-700 rounded-xl shadow-2xl'
    : 'mt-3 border border-slate-700 rounded-lg bg-slate-950/50';
  const heightClass = fullscreen ? 'h-[calc(100%-48px)]' : 'h-[360px]';

  return (
    <div className={containerClass}>
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700">
        <div className="flex items-center gap-3 text-xs text-slate-300">
          <span className="font-semibold">Dependency graph</span>
          <span className="text-slate-500">
            {graph.node_count} cells · {graph.edge_count} edges
          </span>
          <span className="text-slate-500 font-mono truncate max-w-[200px]" title={graph.focal_ref}>
            focal: {graph.focal_ref}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {/* Sheet legend */}
          {sheetOrder.slice(0, 4).map((s, i) => (
            <span key={s} className="flex items-center gap-1 text-[10px] text-slate-400">
              <span className={`w-2 h-2 rounded-full ${SHEET_PALETTE[i % SHEET_PALETTE.length].dot}`} />
              <span className="truncate max-w-[80px]">{s}</span>
            </span>
          ))}
          <button
            onClick={() => setFullscreen(!fullscreen)}
            className="text-xs text-slate-300 hover:text-white border border-slate-600 rounded px-2 py-0.5"
          >
            {fullscreen ? 'Close' : 'Expand'}
          </button>
        </div>
      </div>
      <div className={heightClass}>
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          onNodeClick={onNodeClick}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          proOptions={{ hideAttribution: true }}
          minZoom={0.2}
          maxZoom={2}
        >
          <Background color="#334155" gap={24} />
          <Controls className="!bg-slate-800 !border-slate-700" />
          {fullscreen && <MiniMap pannable zoomable className="!bg-slate-900 !border-slate-700" />}
        </ReactFlow>
      </div>
    </div>
  );
}
