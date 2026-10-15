import { fireEvent, render, screen, within } from '@testing-library/react';
import WorkspaceTopNav from './WorkspaceTopNav';

jest.mock('./AccountControls', () => ({ showIdentity }) => <div>{showIdentity ? 'Full account' : 'Compact account'}</div>);

test('exposes every primary destination and identifies the current page', () => {
  const onNavigate = jest.fn();
  render(<WorkspaceTopNav active="calendar" onNavigate={onNavigate}
    actions={<button>Schedule</button>} status={<span>Service ready</span>} />);

  const navigation = screen.getByRole('navigation', { name: 'Primary navigation' });
  expect(within(navigation).getAllByRole('button')).toHaveLength(7);
  expect(within(navigation).getByRole('button', { name: 'Calendar' })).toHaveAttribute('aria-current', 'page');
  expect(within(navigation).getByRole('button', { name: 'Home' })).not.toHaveAttribute('aria-current');
  expect(screen.getByText('Service ready')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Schedule' })).toBeInTheDocument();
  expect(screen.getByText('Full account')).toBeInTheDocument();

  fireEvent.click(within(navigation).getByRole('button', { name: 'Workflows' }));
  expect(onNavigate).toHaveBeenCalledWith('/workflows');
  fireEvent.click(within(navigation).getByRole('button', { name: 'Knowledge' }));
  expect(onNavigate).toHaveBeenCalledWith('/knowledge');
  fireEvent.click(within(navigation).getByRole('button', { name: 'Operations' }));
  expect(onNavigate).toHaveBeenCalledWith('/operations');
  fireEvent.click(screen.getByRole('button', { name: /^W Workspace$/i }));
  expect(onNavigate).toHaveBeenCalledWith('/');
});

test('hides workspace-wide operations from guest accounts', () => {
  render(<WorkspaceTopNav active="home" role="guest" onNavigate={jest.fn()} />);
  const navigation = screen.getByRole('navigation', { name: 'Primary navigation' });
  expect(within(navigation).queryByRole('button', { name: 'Operations' })).not.toBeInTheDocument();
  expect(within(navigation).getByRole('button', { name: 'Workflows' })).toBeInTheDocument();
});
