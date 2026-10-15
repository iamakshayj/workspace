import { createSavedSearch, searchWorkspace } from './searchService';

afterEach(() => jest.restoreAllMocks());

test('sends enterprise search modes and facets through one endpoint', async () => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ total: 0, results: [] }) });
  await searchWorkspace({ query: 'launch', mode: 'hybrid', types: ['project', 'risk'], statuses: ['active'] });
  const url = new URL(global.fetch.mock.calls[0][0]);
  expect(url.pathname).toBe('/api/v1/search');
  expect(url.searchParams.get('q')).toBe('launch');
  expect(url.searchParams.get('mode')).toBe('hybrid');
  expect(url.searchParams.get('types')).toBe('project,risk');
  expect(url.searchParams.get('statuses')).toBe('active');
});

test('persists reusable saved searches', async () => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({ id: 'saved-1' }) });
  await createSavedSearch({ name: 'Risks', query: 'security', mode: 'keyword', filters: { types: ['risk'] }, shared: false });
  expect(global.fetch.mock.calls[0][0]).toMatch(/\/api\/v1\/search\/saved$/);
  expect(JSON.parse(global.fetch.mock.calls[0][1].body).filters).toEqual({ types: ['risk'] });
});
