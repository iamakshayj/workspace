import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import NodePlanningPanel from './NodePlanningPanel';
import { createNodeWorkItem } from './workService';

jest.mock('./workService', () => ({
  createNodeWorkItem: jest.fn(),
  updateNodePlanning: jest.fn(),
}));

const node = { id: 'node-1', data: { label: 'Approve request', description: 'Manager approves' } };
const emptyPlanning = {
  nodes: { 'node-1': { node_id: 'node-1', revision: 0, primary_item: null, items: [], sprint: null, subflow: null, progress: 0, done_count: 0, item_count: 0, total_points: 0, done_points: 0 } },
  items: [], sprints: [], projects: [], members: [{ id: 'user-1', display_name: 'Demo Admin' }],
};

beforeEach(() => jest.clearAllMocks());

test('creates an epic directly from a flowchart node', async () => {
  const updated = { ...emptyPlanning, nodes: { ...emptyPlanning.nodes } };
  createNodeWorkItem.mockResolvedValue(updated);
  const onPlanningChange = jest.fn();
  render(<NodePlanningPanel projectId="project-1" node={node} planning={emptyPlanning} canManage onPlanningChange={onPlanningChange} onNavigate={jest.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: '＋ Epic' }));
  expect(screen.getByRole('textbox', { name: 'Summary' })).toHaveValue('Approve request');
  fireEvent.click(screen.getByRole('button', { name: 'Create epic' }));
  await waitFor(() => {
    expect(createNodeWorkItem).toHaveBeenCalledWith('project-1', 'node-1', expect.objectContaining({
      summary: 'Approve request', item_type: 'epic', set_primary: true,
    }));
    expect(onPlanningChange).toHaveBeenCalledWith(updated);
  });
});

test('shows epic scope and opens the linked work item', () => {
  const onNavigate = jest.fn();
  const primary = { id: 'epic-1', key: 'FF-1', summary: 'Approval epic', item_type: 'epic', status: 'in_progress' };
  const child = { id: 'story-1', key: 'FF-2', summary: 'Manager review', item_type: 'story', status: 'done', story_points: 3 };
  const planning = { ...emptyPlanning, nodes: { 'node-1': { ...emptyPlanning.nodes['node-1'], primary_item: primary, items: [primary, child], planning_kind: 'epic', progress: 100, done_count: 1, item_count: 1, total_points: 3, done_points: 3 } } };
  render(<NodePlanningPanel projectId="project-1" node={node} planning={planning} canManage onPlanningChange={jest.fn()} onNavigate={onNavigate} />);
  fireEvent.click(screen.getByRole('button', { name: /FF-1 · Approval epic/i }));
  expect(onNavigate).toHaveBeenCalledWith('/work?project=project-1&node=node-1&item=epic-1');
  expect(screen.getByText('1 linked stories, tasks, and subtasks')).toBeInTheDocument();
});
