import React, { useEffect, useMemo, useState } from 'react';
import {
  EMPTY_PROCESS_ANALYTICS,
  eventsFromCsv,
  getProcessAnalytics,
  getProcessImpact,
  importProcessEvents,
  resolveProcessInsight,
} from './processIntelligenceService';

function normalize(value = '') {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function formatDuration(seconds) {
  if (!seconds) return '0m';
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

function downloadSample() {
  const content = 'case_id,activity,timestamp,status,owner,cost\nCASE-001,Request received,2026-08-29T14:00:00Z,completed,Operations,2.50\n';
  const url = URL.createObjectURL(new Blob([content], { type: 'text/csv' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'flowforge-events-sample.csv';
  link.click();
  URL.revokeObjectURL(url);
}

export default function ProcessIntelligencePanel({
  open,
  onClose,
  projectId,
  nodes,
  canManage,
  analytics = EMPTY_PROCESS_ANALYTICS,
  onAnalyticsChange,
  onSelectNode,
}) {
  const [tab, setTab] = useState('overview');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [filename, setFilename] = useState('events.csv');
  const [events, setEvents] = useState([]);
  const [mapping, setMapping] = useState({});
  const [impactQuery, setImpactQuery] = useState('');
  const [impact, setImpact] = useState({ matches: [], dependency_summary: {} });

  const nodeById = useMemo(() => Object.fromEntries(nodes.map((node) => [node.id, node])), [nodes]);
  const activities = useMemo(() => [...new Set(events.map((event) => event.activity))].sort(), [events]);
  const openInsights = analytics.insights.filter((insight) => insight.status === 'open');

  useEffect(() => {
    if (!open || !projectId) return;
    setLoading(true);
    setError('');
    getProcessAnalytics(projectId)
      .then(onAnalyticsChange)
      .catch((requestError) => setError(requestError.message))
      .finally(() => setLoading(false));
  }, [onAnalyticsChange, open, projectId]);

  const chooseFile = async (file) => {
    if (!file) return;
    setError('');
    try {
      const parsed = eventsFromCsv(await file.text());
      const labels = Object.fromEntries(nodes.map((node) => [normalize(node.data?.label), node.id]));
      setEvents(parsed);
      setFilename(file.name);
      setMapping(Object.fromEntries(
        [...new Set(parsed.map((event) => event.activity))]
          .map((activity) => [activity, labels[normalize(activity)] || ''])
      ));
      setTab('import');
    } catch (parseError) {
      setEvents([]);
      setError(parseError.message);
    }
  };

  const importEvents = async () => {
    setBusy(true);
    setError('');
    try {
      await importProcessEvents(projectId, {
        filename,
        activity_node_map: Object.fromEntries(Object.entries(mapping).filter(([, nodeId]) => nodeId)),
        events,
      });
      const updated = await getProcessAnalytics(projectId);
      onAnalyticsChange(updated);
      setEvents([]);
      setMapping({});
      setTab('overview');
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  };

  const resolveInsight = async (insightId) => {
    setBusy(true);
    try {
      await resolveProcessInsight(projectId, insightId);
      onAnalyticsChange(await getProcessAnalytics(projectId));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  };

  const searchImpact = async () => {
    setBusy(true);
    setError('');
    try {
      setImpact(await getProcessImpact(impactQuery));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;
  return <aside className="intelligence-panel" aria-label="Process intelligence">
    <header>
      <div><p className="eyebrow">Process intelligence</p><h2>Observed vs designed</h2></div>
      <button className="icon-button" aria-label="Close process intelligence" onClick={onClose}>×</button>
    </header>
    <nav aria-label="Process intelligence views">
      <button className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>Overview {openInsights.length > 0 && <span>{openInsights.length}</span>}</button>
      <button className={tab === 'import' ? 'active' : ''} onClick={() => setTab('import')}>Import</button>
      <button className={tab === 'impact' ? 'active' : ''} onClick={() => setTab('impact')}>Impact</button>
    </nav>
    {error && <div className="intelligence-error" role="alert">{error}</div>}
    {tab === 'overview' && <div className="intelligence-scroll">
      <section className="metric-grid">
        <span><strong>{analytics.case_count.toLocaleString()}</strong><small>Cases</small></span>
        <span><strong>{analytics.event_count.toLocaleString()}</strong><small>Events</small></span>
        <span><strong>{analytics.conformance_rate}%</strong><small>Conformance</small></span>
        <span><strong>{formatDuration(analytics.average_case_cycle_seconds)}</strong><small>Avg cycle</small></span>
      </section>
      {loading && <p className="intelligence-empty">Loading process evidence…</p>}
      {!loading && analytics.event_count === 0 && <div className="intelligence-empty">
        <strong>No execution data yet</strong>
        <p>Import a CSV event log to reveal bottlenecks, failures, SLA misses, and process drift.</p>
        {canManage && <button className="button primary" onClick={() => setTab('import')}>Import events</button>}
      </div>}
      {openInsights.length > 0 && <section className="intelligence-section">
        <h3>Attention needed</h3>
        {openInsights.map((insight) => <article className={`drift-card ${insight.severity}`} key={insight.id}>
          <div><span>{insight.severity}</span><strong>{insight.title}</strong></div>
          <p>{insight.description}</p>
          <footer>
            {insight.node_id && <button onClick={() => onSelectNode(insight.node_id)}>Show step</button>}
            {canManage && <button disabled={busy} onClick={() => resolveInsight(insight.id)}>Resolve</button>}
          </footer>
        </article>)}
      </section>}
      {analytics.node_metrics.length > 0 && <section className="intelligence-section">
        <h3>Step performance</h3>
        {analytics.node_metrics.map((metric) => <button className="node-metric-row" key={metric.node_id}
          onClick={() => onSelectNode(metric.node_id)}>
          <span><strong>{nodeById[metric.node_id]?.data?.label || metric.node_id}</strong><small>{metric.count} executions</small></span>
          <span><b>{formatDuration(metric.average_wait_seconds)}</b><small>avg wait</small></span>
          {(metric.failure_count > 0 || metric.sla_breach_count > 0) && <i>{metric.failure_count + metric.sla_breach_count}</i>}
        </button>)}
      </section>}
    </div>}
    {tab === 'import' && <div className="intelligence-scroll">
      <section className="import-card">
        <h3>CSV event log</h3>
        <p>Required columns: <code>case_id</code>, <code>activity</code>, and <code>timestamp</code>. Optional: status, owner, cost.</p>
        <div><label className="button secondary upload-button">Choose CSV<input type="file" accept=".csv,text/csv" onChange={(event) => chooseFile(event.target.files?.[0])} /></label>
          <button className="text-button" onClick={downloadSample}>Download sample</button></div>
      </section>
      {events.length > 0 && <section className="mapping-card">
        <header><strong>{filename}</strong><span>{events.length} events · {activities.length} activities</span></header>
        <h3>Map activities to steps</h3>
        {activities.map((activity) => <label key={activity}><span>{activity}</span><select value={mapping[activity] || ''}
          onChange={(event) => setMapping((current) => ({ ...current, [activity]: event.target.value }))}>
          <option value="">Leave unmapped</option>
          {nodes.filter((node) => node.data?.type !== 'swimlane').map((node) => <option key={node.id} value={node.id}>{node.data?.label}</option>)}
        </select></label>)}
        <button className="button primary" disabled={busy} onClick={importEvents}>{busy ? 'Analyzing…' : 'Import and analyze'}</button>
      </section>}
      {analytics.imports.length > 0 && <section className="intelligence-section"><h3>Import history</h3>
        {analytics.imports.map((item) => <div className="import-history" key={item.id}><span><strong>{item.filename}</strong><small>{new Date(item.created_at).toLocaleString()}</small></span><b>{item.event_count} events</b></div>)}
      </section>}
    </div>}
    {tab === 'impact' && <div className="intelligence-scroll">
      <section className="impact-search"><h3>Cross-process dependency search</h3>
        <p>Find every process step that relies on a system, vendor, control, policy, owner, or data class.</p>
        <div><input value={impactQuery} placeholder="Example: Salesforce or CTRL-12" onChange={(event) => setImpactQuery(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter') searchImpact(); }} />
          <button className="button primary" disabled={busy} onClick={searchImpact}>Search</button></div>
      </section>
      {impact.matches.map((match) => <a className="impact-result" key={`${match.project_id}-${match.node_id}-${match.dependency_type}`}
        href={`/projects/${match.project_id}`}>
        <span><strong>{match.node_label}</strong><small>{match.project_title}</small></span>
        <span><b>{match.dependency_type.replace('_', ' ')}</b><small>{match.dependency_value}</small></span>
      </a>)}
      {impactQuery && !busy && impact.matches.length === 0 && <p className="intelligence-empty">No matching dependencies found.</p>}
    </div>}
  </aside>;
}
