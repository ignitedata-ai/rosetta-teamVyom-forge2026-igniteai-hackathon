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

// --- Colors per sheet (light theme — soft tinted backgrounds) ---
const SHEET_PALETTE = [
  { bg: 'bg-[#f5f0ff]', border: 'border-[#8243EA]', dot: 'bg-[#8243EA]' },
  { bg: 'bg-emerald-50', border: 'border-emerald-500', dot: 'bg-emerald-500' },
  { bg: 'bg-amber-50', border: 'border-amber-500', dot: 'bg-amber-500' },
  { bg: 'bg-rose-50', border: 'border-rose-500', dot: 'bg-rose-500' },
  { bg: 'bg-sky-50', border: 'border-sky-500', dot: 'bg-sky-500' },
  { bg: 'bg-fuchsia-50', border: 'border-fuchsia-500', dot: 'bg-fuchsia-500' },
];

function sheetColor(sheet: string, sheetOrder: string[]) {
  const idx = sheetOrder.indexOf(sheet);
  return SHEET_PALETTE[(idx >= 0 ? idx : 0) % SHEET_PALETTE.length];
}

// --- Custom node component ---
function CellNode({ data }: NodeProps<Node<DependencyGraphNodeData & { palette: typeof SHEET_PALETTE[0] }>>) {
  const palette = data.palette;
  const focalRing = data.is_focal ? 'ring-2 ring-[#5b21b6] ring-offset-1 ring-offset-white' : '';
  return (
    <div
      className={`${palette.bg} ${palette.border} ${focalRing} border rounded-lg px-3 py-2 text-[#0f1020] shadow-[0_4px_14px_rgba(15,16,32,0.08)] w-[220px]`}
      title={data.ref}
    >
      <Handle type="target" position={Position.Left} className="!bg-[#9a9caf]" />
      <div className="flex items-center gap-2 mb-1">
        <span className={`w-2 h-2 rounded-full ${palette.dot}`} />
        <span className="text-[10px] font-mono text-[#5a5c70] truncate">{data.sheet}</span>
        <span className="text-[10px] font-mono text-[#7a7d92] ml-auto">{data.coord}</span>
      </div>
      {data.label && (
        <div className="text-sm font-semibold truncate mb-0.5">{data.label}</div>
      )}
      {data.value != null && (
        <div className="text-xs text-emerald-700 font-mono truncate">{data.value}</div>
      )}
      {data.formula && (
        <div className="text-[10px] text-[#5a5c70] font-mono truncate mt-1" title={data.formula}>
          ={data.formula}
        </div>
      )}
      {data.is_hardcoded && (
        <div className="text-[9px] text-amber-700 mt-1">⚠ hardcoded</div>
      )}
      {data.is_volatile && (
        <div className="text-[9px] text-orange-700 mt-1">⚡ volatile</div>
      )}
      {data.named_range && (
        <div className="text-[9px] text-[#5b21b6] mt-1">⬩ {data.named_range}</div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-[#9a9caf]" />
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
      style: { stroke: '#9a9caf', strokeWidth: 1.5 },
    }));
    return { rfNodes: layout(rawNodes, rawEdges), rfEdges: rawEdges };
  }, [graph, sheetOrder]);

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    const data = node.data as DependencyGraphNodeData;
    console.log('Cell:', data.ref, data);
  }, []);

  const containerClass = fullscreen
    ? 'fixed inset-4 z-50 bg-white border border-[#e3e5ee] rounded-xl shadow-[0_24px_80px_rgba(15,16,32,0.2)]'
    : 'mt-3 border border-[#e3e5ee] rounded-lg bg-[#f9f8fd]';
  const heightClass = fullscreen ? 'h-[calc(100%-48px)]' : 'h-[360px]';

  return (
    <div className={containerClass}>
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#e3e5ee] flex-wrap gap-y-1">
        <div className="flex items-center gap-3 text-xs text-[#5a5c70]">
          <span className="text-[10px] uppercase tracking-[0.18em] text-[#0f1020] font-semibold">Dependency graph</span>
          <span className="text-[#7a7d92]">
            {graph.node_count} cells · {graph.edge_count} edges
          </span>
          <span className="text-[#7a7d92] font-mono truncate max-w-[200px]" title={graph.focal_ref}>
            focal: {graph.focal_ref}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {sheetOrder.slice(0, 4).map((s, i) => (
            <span key={s} className="flex items-center gap-1 text-[10px] text-[#5a5c70]">
              <span className={`w-2 h-2 rounded-full ${SHEET_PALETTE[i % SHEET_PALETTE.length].dot}`} />
              <span className="truncate max-w-[80px]">{s}</span>
            </span>
          ))}
          <button
            onClick={() => setFullscreen(!fullscreen)}
            className="text-[10px] uppercase tracking-[0.16em] font-semibold text-[#5a5c70] hover:text-[#5b21b6] border border-[#e3e5ee] rounded px-2 py-0.5"
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
          <Background color="#d0d3df" gap={24} />
          <Controls className="!bg-white !border-[#e3e5ee]" />
          {fullscreen && <MiniMap pannable zoomable className="!bg-white !border-[#e3e5ee]" />}
        </ReactFlow>
      </div>
    </div>
  );
}
