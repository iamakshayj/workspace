import React from 'react';

export const DIAGRAM_LIBRARY = [
  {
    id: 'basics', label: 'Basics', items: [
      { id: 'process', label: 'Process step', type: 'process', shape: 'rounded', width: 180, height: 76 },
      { id: 'free_text', label: 'Free text', type: 'process', shape: 'text', width: 190, height: 54 },
      { id: 'rectangle', label: 'Rectangle', type: 'process', shape: 'rectangle', width: 180, height: 82 },
      { id: 'ellipse', label: 'Ellipse', type: 'process', shape: 'ellipse', width: 170, height: 92 },
      { id: 'diamond', label: 'Diamond', type: 'decision', shape: 'diamond', width: 150, height: 120 },
      { id: 'document', label: 'Document', type: 'document', shape: 'document', width: 180, height: 92 },
      { id: 'subprocess', label: 'Subprocess', type: 'subprocess', shape: 'rounded', width: 230, height: 104 },
      { id: 'swimlane', label: 'Swimlane', type: 'swimlane', shape: 'rectangle', width: 680, height: 240, color: '#F6F8FB' },
    ],
  },
  {
    id: 'bpmn', label: 'BPMN', items: [
      { id: 'bpmn_start_event', label: 'Start event', type: 'start', shape: 'ellipse', symbol: 'bpmn_start', width: 96, height: 96 },
      { id: 'bpmn_end_event', label: 'End event', type: 'end', shape: 'ellipse', symbol: 'bpmn_end', width: 96, height: 96 },
      { id: 'bpmn_timer_event', label: 'Timer event', type: 'wait', shape: 'ellipse', symbol: 'bpmn_timer', width: 104, height: 104 },
      { id: 'bpmn_message_event', label: 'Message event', type: 'wait', shape: 'ellipse', symbol: 'bpmn_message', width: 104, height: 104 },
      { id: 'bpmn_user_task', label: 'User task', type: 'process', shape: 'rounded', symbol: 'bpmn_user_task', width: 190, height: 92 },
      { id: 'bpmn_service_task', label: 'Service task', type: 'process', shape: 'rounded', symbol: 'bpmn_service_task', width: 190, height: 92 },
      { id: 'bpmn_exclusive_gateway', label: 'Exclusive gateway', type: 'decision', shape: 'diamond', symbol: 'bpmn_exclusive_gateway', width: 120, height: 120 },
      { id: 'bpmn_parallel_gateway', label: 'Parallel gateway', type: 'decision', shape: 'diamond', symbol: 'bpmn_parallel_gateway', width: 120, height: 120 },
      { id: 'bpmn_data_object', label: 'Data object', type: 'document', shape: 'document', symbol: 'bpmn_data_object', width: 150, height: 108 },
      { id: 'bpmn_data_store', label: 'Data store', type: 'external_system', shape: 'ellipse', symbol: 'bpmn_data_store', width: 150, height: 104 },
    ],
  },
  {
    id: 'enterprise', label: 'Enterprise', items: [
      { id: 'enterprise_database', label: 'Database', type: 'external_system', shape: 'rounded', symbol: 'enterprise_database', width: 180, height: 96 },
      { id: 'enterprise_server', label: 'Server', type: 'external_system', shape: 'rectangle', symbol: 'enterprise_server', width: 180, height: 96 },
      { id: 'enterprise_cloud', label: 'Cloud service', type: 'external_system', shape: 'rounded', symbol: 'enterprise_cloud', width: 190, height: 96 },
      { id: 'enterprise_api', label: 'API', type: 'external_system', shape: 'rounded', symbol: 'enterprise_api', width: 170, height: 88 },
      { id: 'enterprise_user', label: 'User / role', type: 'process', shape: 'rounded', symbol: 'enterprise_user', width: 170, height: 92 },
      { id: 'enterprise_document', label: 'Business document', type: 'document', shape: 'document', symbol: 'enterprise_document', width: 180, height: 100 },
      { id: 'enterprise_queue', label: 'Message queue', type: 'external_system', shape: 'rounded', symbol: 'enterprise_queue', width: 190, height: 94 },
      { id: 'enterprise_system', label: 'Application system', type: 'external_system', shape: 'rectangle', symbol: 'enterprise_system', width: 190, height: 98 },
    ],
  },
  {
    id: 'software', label: 'UML & data', items: [
      { id: 'uml_class', label: 'UML class', type: 'process', shape: 'rectangle', symbol: 'uml_class', width: 210, height: 130 },
      { id: 'uml_actor', label: 'UML actor', type: 'process', shape: 'rounded', symbol: 'uml_actor', width: 145, height: 110 },
      { id: 'sequence_lifeline', label: 'Sequence lifeline', type: 'swimlane', shape: 'rectangle', symbol: 'sequence_lifeline', width: 170, height: 260 },
      { id: 'erd_entity', label: 'ERD entity', type: 'document', shape: 'rectangle', symbol: 'erd_entity', width: 220, height: 125 },
      { id: 'architecture_component', label: 'Architecture component', type: 'external_system', shape: 'rectangle', symbol: 'architecture_component', width: 210, height: 105 },
      { id: 'network_device', label: 'Network device', type: 'external_system', shape: 'rounded', symbol: 'network_device', width: 175, height: 98 },
    ],
  },
  {
    id: 'planning', label: 'Maps & organization', items: [
      { id: 'mind_topic', label: 'Mind-map topic', type: 'process', shape: 'ellipse', symbol: 'mind_topic', width: 180, height: 82 },
      { id: 'org_unit', label: 'Org-chart role', type: 'process', shape: 'rounded', symbol: 'org_unit', width: 185, height: 96 },
      { id: 'sticky_note', label: 'Sticky note', type: 'process', shape: 'rectangle', symbol: 'sticky_note', width: 180, height: 150, color: '#FFF1C7' },
      { id: 'comment_card', label: 'Comment card', type: 'document', shape: 'rounded', symbol: 'comment_card', width: 190, height: 105 },
    ],
  },
];

const SYMBOL_NAMES = Object.fromEntries(
  DIAGRAM_LIBRARY.flatMap((category) => category.items)
    .filter((item) => item.symbol)
    .map((item) => [item.symbol, item.label])
);

export function symbolName(symbol) {
  return SYMBOL_NAMES[symbol] || '';
}

function DatabaseIcon() {
  return <><ellipse cx="16" cy="7" rx="10" ry="4" /><path d="M6 7v9c0 2.2 4.5 4 10 4s10-1.8 10-4V7M6 12c0 2.2 4.5 4 10 4s10-1.8 10-4M6 17v8c0 2.2 4.5 4 10 4s10-1.8 10-4v-9" /></>;
}

export function DiagramSymbol({ symbol }) {
  if (!symbol) return null;
  let content;
  if (symbol === 'bpmn_start') content = <circle cx="16" cy="16" r="11" />;
  else if (symbol === 'bpmn_end') content = <><circle cx="16" cy="16" r="11" /><circle cx="16" cy="16" r="8" /></>;
  else if (symbol === 'bpmn_timer') content = <><circle cx="16" cy="16" r="11" /><path d="M16 9v7l5 3M11 6.3l1.2 2M21 6.3l-1.2 2M25.7 11l-2 1.2M6.3 11l2 1.2M16 24v2" /></>;
  else if (symbol === 'bpmn_message') content = <><circle cx="16" cy="16" r="12" /><path d="M8 11h16v11H8zM8 12l8 6 8-6" /></>;
  else if (symbol === 'bpmn_user_task' || symbol === 'enterprise_user') content = <><circle cx="16" cy="10" r="4" /><path d="M8 26c.8-6 3.5-9 8-9s7.2 3 8 9M11 18l5 5 5-5" /></>;
  else if (symbol === 'bpmn_service_task') content = <><circle cx="16" cy="16" r="6" /><path d="M16 5v4M16 23v4M5 16h4M23 16h4M8.2 8.2l2.8 2.8M21 21l2.8 2.8M23.8 8.2 21 11M11 21l-2.8 2.8" /></>;
  else if (symbol === 'bpmn_exclusive_gateway') content = <path d="m9 9 14 14M23 9 9 23" />;
  else if (symbol === 'bpmn_parallel_gateway') content = <path d="M16 7v18M7 16h18" />;
  else if (symbol === 'bpmn_data_object' || symbol === 'enterprise_document') content = <path d="M9 4h10l5 5v19H9zM19 4v6h5M12 16h9M12 21h9" />;
  else if (symbol === 'bpmn_data_store' || symbol === 'enterprise_database') content = <DatabaseIcon />;
  else if (symbol === 'enterprise_server') content = <><rect x="6" y="5" width="20" height="9" rx="2" /><rect x="6" y="18" width="20" height="9" rx="2" /><circle cx="10" cy="9.5" r="1" /><circle cx="10" cy="22.5" r="1" /><path d="M14 10h8M14 23h8" /></>;
  else if (symbol === 'enterprise_cloud') content = <path d="M8 24h16a6 6 0 0 0 1-11.9A9 9 0 0 0 8.7 10 7 7 0 0 0 8 24Z" />;
  else if (symbol === 'enterprise_api') content = <><path d="M11 7 6 16l5 9M21 7l5 9-5 9M18 5l-4 22" /></>;
  else if (symbol === 'enterprise_queue') content = <><circle cx="8" cy="10" r="3" /><circle cx="8" cy="22" r="3" /><circle cx="24" cy="16" r="3" /><path d="M11 10h5a5 5 0 0 1 5 5M11 22h5a5 5 0 0 0 5-5" /></>;
  else if (symbol === 'uml_class') content = <><rect x="5" y="4" width="22" height="24" rx="1" /><path d="M5 11h22M5 19h22M9 8h8M9 15h12M9 23h10" /></>;
  else if (symbol === 'uml_actor') content = <><circle cx="16" cy="7" r="4" /><path d="M16 11v10M8 15h16M16 21l-7 8M16 21l7 8" /></>;
  else if (symbol === 'sequence_lifeline') content = <><rect x="6" y="3" width="20" height="8" rx="1" /><path d="M16 11v18M12 17h8M12 23h8" strokeDasharray="2 2" /></>;
  else if (symbol === 'erd_entity') content = <><rect x="4" y="5" width="24" height="22" rx="1" /><path d="M4 12h24M11 12v15M7 9h10M14 17h10M14 22h8" /></>;
  else if (symbol === 'architecture_component') content = <><rect x="7" y="6" width="20" height="21" rx="2" /><rect x="3" y="10" width="8" height="5" /><rect x="3" y="19" width="8" height="5" /></>;
  else if (symbol === 'network_device') content = <><rect x="5" y="8" width="22" height="16" rx="4" /><path d="M10 13h12M10 19h12M8 28h16M12 24v4M20 24v4" /></>;
  else if (symbol === 'mind_topic') content = <><ellipse cx="16" cy="16" rx="10" ry="6" /><path d="M6 16H2M30 16h-4M16 10V5M16 27v-5" /></>;
  else if (symbol === 'org_unit') content = <><circle cx="16" cy="9" r="4" /><path d="M9 22c1-5 3-7 7-7s6 2 7 7M16 22v6M8 28h16" /></>;
  else if (symbol === 'sticky_note') content = <><path d="M6 4h20v16l-8 8H6zM18 28v-8h8" /><path d="M10 10h12M10 15h10" /></>;
  else if (symbol === 'comment_card') content = <><path d="M5 6h22v16H15l-6 5v-5H5z" /><path d="M10 12h12M10 17h8" /></>;
  else content = <><rect x="5" y="6" width="22" height="17" rx="2" /><path d="M10 28h12M16 23v5M9 11h14" /></>;
  return <svg className="diagram-symbol-icon" viewBox="0 0 32 32" aria-hidden="true">{content}</svg>;
}
