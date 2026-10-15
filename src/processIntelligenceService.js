import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  const body = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) {
    notifyIfUnauthorized(response);
    throw new Error(body?.detail || 'Process intelligence request failed.');
  }
  return body;
}

export const EMPTY_PROCESS_ANALYTICS = {
  event_count: 0,
  case_count: 0,
  mapped_event_count: 0,
  conformance_rate: 100,
  average_case_cycle_seconds: 0,
  node_metrics: [],
  edge_metrics: [],
  insights: [],
  imports: [],
};

export function getProcessAnalytics(projectId) {
  return request(`/api/v1/projects/${encodeURIComponent(projectId)}/process-analytics`).then((body) => ({
    ...EMPTY_PROCESS_ANALYTICS,
    ...(body && !Array.isArray(body) ? body : {}),
    node_metrics: Array.isArray(body?.node_metrics) ? body.node_metrics : [],
    edge_metrics: Array.isArray(body?.edge_metrics) ? body.edge_metrics : [],
    insights: Array.isArray(body?.insights) ? body.insights : [],
    imports: Array.isArray(body?.imports) ? body.imports : [],
  }));
}

export function importProcessEvents(projectId, payload) {
  return request(`/api/v1/projects/${encodeURIComponent(projectId)}/process-events/imports`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function resolveProcessInsight(projectId, insightId) {
  return request(
    `/api/v1/projects/${encodeURIComponent(projectId)}/process-insights/${encodeURIComponent(insightId)}/resolve`,
    { method: 'POST' }
  );
}

export function deleteProcessEventImport(projectId, importId) {
  return request(
    `/api/v1/projects/${encodeURIComponent(projectId)}/process-events/imports/${encodeURIComponent(importId)}`,
    { method: 'DELETE' }
  );
}

export function getProcessImpact(query = '') {
  return request(`/api/v1/process-impact?query=${encodeURIComponent(query)}`);
}

export function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (character === '"' && quoted && text[index + 1] === '"') {
      cell += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (character === ',' && !quoted) {
      row.push(cell.trim());
      cell = '';
    } else if ((character === '\n' || character === '\r') && !quoted) {
      if (character === '\r' && text[index + 1] === '\n') index += 1;
      row.push(cell.trim());
      if (row.some(Boolean)) rows.push(row);
      row = [];
      cell = '';
    } else {
      cell += character;
    }
  }
  row.push(cell.trim());
  if (row.some(Boolean)) rows.push(row);
  return rows;
}

function headerKey(value) {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
}

export function eventsFromCsv(text) {
  const rows = parseCsv(text);
  if (rows.length < 2) throw new Error('The CSV needs a header row and at least one event.');
  const headers = rows[0].map(headerKey);
  const column = (...names) => names.map((name) => headers.indexOf(name)).find((index) => index >= 0);
  const caseColumn = column('case_id', 'case', 'instance_id', 'process_id');
  const activityColumn = column('activity', 'step', 'event', 'task');
  const timeColumn = column('occurred_at', 'timestamp', 'time', 'event_time', 'date');
  if (caseColumn === undefined || activityColumn === undefined || timeColumn === undefined) {
    throw new Error('CSV columns case_id, activity, and timestamp are required.');
  }
  const statusColumn = column('status', 'result', 'outcome');
  const ownerColumn = column('owner', 'assignee', 'user');
  const costColumn = column('cost', 'amount');
  return rows.slice(1).map((values, index) => {
    const occurredAt = new Date(values[timeColumn]);
    if (!values[caseColumn] || !values[activityColumn] || Number.isNaN(occurredAt.getTime())) {
      throw new Error(`Row ${index + 2} has a missing case, activity, or invalid timestamp.`);
    }
    const event = {
      case_id: values[caseColumn],
      activity: values[activityColumn],
      occurred_at: occurredAt.toISOString(),
    };
    if (statusColumn !== undefined && values[statusColumn]) event.status = values[statusColumn];
    if (ownerColumn !== undefined && values[ownerColumn]) event.owner = values[ownerColumn];
    if (costColumn !== undefined && values[costColumn]) {
      const cost = Number(values[costColumn]);
      if (!Number.isFinite(cost) || cost < 0) throw new Error(`Row ${index + 2} has an invalid cost.`);
      event.cost = cost;
    }
    return event;
  });
}
