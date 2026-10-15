import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import ProjectExportMenu from './ProjectExportMenu';
import { createProjectArtifact } from './flowchartService';


jest.mock('./flowchartService', () => ({ createProjectArtifact: jest.fn() }));

afterEach(() => jest.clearAllMocks());

test('offers immediate PNG and queued project exports', async () => {
  const onExportPng = jest.fn();
  createProjectArtifact.mockResolvedValue({
    filename: 'approval-flowchart.svg',
    download_url: '/api/v1/projects/project-1/artifacts/artifact-1/download',
  });
  const click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  render(<ProjectExportMenu projectId="project-1" canManage onExportPng={onExportPng} />);

  fireEvent.click(screen.getByRole('button', { name: /export png or project package/i }));
  const menu = screen.getByRole('menu', { name: /export options/i });
  expect(menu.parentElement).toBe(document.body);
  expect(menu.style.width).toMatch(/px$/);
  expect(screen.getByRole('menuitem', { name: /png image/i })).toBeInTheDocument();
  expect(screen.getByRole('menuitem', { name: /evidence package/i })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('menuitem', { name: /svg diagram/i }));

  await waitFor(() => expect(createProjectArtifact).toHaveBeenCalledWith('project-1', {
    kind: 'export', format: 'svg',
  }));
  await waitFor(() => expect(click).toHaveBeenCalled());
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(
    /approval-flowchart.svg download started/i
  ));
  click.mockRestore();
});

test('keeps server exports disabled until the flowchart is saved', () => {
  render(<ProjectExportMenu projectId={null} canManage={false} onExportPng={jest.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: /export png or project package/i }));

  expect(screen.getByRole('menuitem', { name: /svg diagram/i })).toBeDisabled();
  expect(screen.queryByRole('menuitem', { name: /evidence package/i })).not.toBeInTheDocument();
  expect(screen.getByText(/save the workflow/i)).toBeInTheDocument();
});
