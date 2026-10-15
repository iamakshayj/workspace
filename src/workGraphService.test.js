import { createRelationship, getRelatedItems } from './workGraphService';

afterEach(() => jest.restoreAllMocks());

test('loads bidirectional multi-hop related objects', async () => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ nodes: [], edges: [] }) });
  await getRelatedItems('project', 'project-1', { depth: 3, direction: 'both', relationshipTypes: ['blocks', 'documented_by'] });
  const url = new URL(global.fetch.mock.calls[0][0]);
  expect(url.pathname).toBe('/api/v1/work-graph/objects/project/project-1/related');
  expect(url.searchParams.get('depth')).toBe('3');
  expect(url.searchParams.get('direction')).toBe('both');
  expect(url.searchParams.get('relationship_types')).toBe('blocks,documented_by');
});

test('creates canonical cross-object relationships', async () => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({ id: 'edge-1' }) });
  const payload = { source_type: 'project', source_id: 'p1', target_type: 'document', target_id: 'd1', relationship_type: 'documented_by' };
  await createRelationship(payload);
  expect(JSON.parse(global.fetch.mock.calls[0][1].body)).toEqual(payload);
});
