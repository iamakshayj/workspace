import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import EnterpriseSearch from './EnterpriseSearch';
import * as searchService from './searchService';
import * as graphService from './workGraphService';

jest.mock('./searchService');
jest.mock('./workGraphService');

beforeEach(() => {
  searchService.getSavedSearches.mockResolvedValue([{
    id: 'saved-1', name: 'Launch work', query: 'launch', mode: 'hybrid',
    filters: { types: ['project'] }, can_edit: true,
  }]);
  searchService.getRecentSearches.mockResolvedValue([{
    id: 'recent-1', query: 'customer', mode: 'keyword', filters: {}, result_count: 2,
  }]);
  searchService.searchWorkspace.mockResolvedValue({
    total: 1,
    facets: { types: [{ value: 'project', count: 1 }], statuses: [{ value: 'active', count: 1 }], projects: [] },
    results: [{ id: 'project-1', type: 'project', title: 'Customer launch', snippet: 'Release the portal', status: 'active', url: '/projects/project-1' }],
  });
  graphService.getRelatedItems.mockResolvedValue({
    nodes: [{ id: 'work-1', type: 'work_item', title: 'Deploy portal', status: 'in_progress', depth: 1, url: '/work?item=work-1' }],
    edges: [{ id: 'edge-1' }], truncated: false,
  });
  graphService.getObjectHistory.mockResolvedValue({ events: [{ id: 'event-1', action: 'project.updated', created_at: '2026-09-03T12:00:00Z' }] });
});

afterEach(() => jest.clearAllMocks());

test('opens global search, applies a saved search, and previews related graph items', async () => {
  const onNavigate = jest.fn();
  render(<EnterpriseSearch onNavigate={onNavigate} />);
  fireEvent.click(screen.getByRole('button', { name: 'Search workspace' }));
  expect(await screen.findByRole('heading', { name: 'Saved searches' })).toBeInTheDocument();
  expect(await screen.findByText('Launch work')).toBeInTheDocument();
  expect(await screen.findByText('customer')).toBeInTheDocument();

  fireEvent.click(screen.getByText('Launch work'));
  await waitFor(() => expect(searchService.searchWorkspace).toHaveBeenCalledWith(expect.objectContaining({
    query: 'launch', mode: 'hybrid', types: ['project'],
  })));
  fireEvent.click(await screen.findByRole('button', { name: /Customer launch/ }));
  expect(await screen.findByText('Deploy portal')).toBeInTheDocument();
  expect(graphService.getRelatedItems).toHaveBeenCalledWith('project', 'project-1', expect.objectContaining({ depth: 1 }));

  fireEvent.click(screen.getByRole('button', { name: 'Open Project' }));
  expect(onNavigate).toHaveBeenCalledWith('/projects/project-1');
});

test('opens with the command-k shortcut', async () => {
  render(<EnterpriseSearch onNavigate={jest.fn()} />);
  fireEvent.keyDown(window, { key: 'k', metaKey: true });
  expect(await screen.findByRole('searchbox', { name: 'Search everything' })).toHaveFocus();
});
