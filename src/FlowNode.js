import React from 'react';
import { Handle, NodeResizer, Position } from 'reactflow';
import { DiagramSymbol } from './DiagramSymbols';

const HANDLE_POSITIONS = [
  ['top', Position.Top],
  ['right', Position.Right],
  ['bottom', Position.Bottom],
  ['left', Position.Left],
];

function FlowNode({ data, selected }) {
  const shape = data.shape || 'rounded';
  const textOnly = shape === 'text';
  const metric = data.intelligence;
  const planning = data.planning;
  const alertCount = (metric?.failure_count || 0) + (metric?.sla_breach_count || 0);
  return (
    <div
      role="group"
      aria-label={`${data.type || 'process'}: ${data.label || 'Untitled step'}${data.owner ? `, owner ${data.owner}` : ''}`}
      className={`flow-node flow-node-${data.type || 'process'} flow-node-shape-${shape} ${data.symbol ? 'has-symbol' : ''} ${metric ? 'observed' : ''} ${alertCount ? 'observed-alert' : ''} ${planning?.planning_kind ? 'delivery-planned' : ''} ${selected ? 'selected' : ''}`}
      style={data.color ? { '--node-color': data.color } : undefined}
    >
      <NodeResizer isVisible={Boolean(selected && data.canResize)} minWidth={80} minHeight={44}
        maxWidth={720} maxHeight={520} lineClassName="node-resizer-line" handleClassName="node-resizer-handle" />
      {!textOnly && HANDLE_POSITIONS.map(([id, position]) => (
        <Handle key={id} id={id} type="source" position={position} aria-label={`Connect from ${id} side`} className={`flow-handle flow-handle-${id}`} />
      ))}
      {data.symbol && <DiagramSymbol symbol={data.symbol} />}
      {!textOnly && !data.symbol && <div className="flow-node-type">{(data.type || 'process').replace('_', ' ')}</div>}
      <div className="flow-node-label">{data.label}</div>
      {data.owner && <div className="flow-node-owner">{data.owner}</div>}
      {(data.control_id || data.risk_level === 'high' || data.risk_level === 'critical') && <div className={`flow-node-control ${data.risk_level || ''}`}>
        {data.control_id || `${data.risk_level} risk`}
      </div>}
      {metric && <div className="flow-node-observed"><strong>{metric.count}×</strong>{alertCount > 0 && <span>! {alertCount}</span>}</div>}
      {data.attachmentCount > 0 && <div className="flow-node-attachments">⌕ {data.attachmentCount}</div>}
      {planning?.planning_kind && <div className={`flow-node-delivery ${planning.planning_kind}`} title={`${planning.planning_kind} · ${planning.progress}% complete`}>
        <span>{planning.primary_item?.key || planning.planning_kind}</span><strong>{planning.progress}%</strong>
        <i><b style={{ width: `${planning.progress}%` }} /></i>
        {planning.subflow && <em title={`Sub-workflow: ${planning.subflow.title}`}>↳</em>}
      </div>}
    </div>
  );
}

export default React.memo(FlowNode);
