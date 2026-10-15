import { act, fireEvent, render, screen } from '@testing-library/react';
import { ThemeProvider, useTheme, validThemePreference } from './ThemeProvider';

function ThemeHarness() {
  const { preference, resolvedTheme, setThemePreference } = useTheme();
  return <div><span>{preference}:{resolvedTheme}</span>
    <button onClick={() => setThemePreference('light')}>Use light</button>
  </div>;
}

test('falls back to the system preference for invalid stored values', () => {
  expect(validThemePreference('sepia')).toBe('system');
  expect(validThemePreference(null)).toBe('system');
  expect(validThemePreference('dark')).toBe('dark');
});

test('follows the system theme and allows an explicit override', () => {
  const media = { matches: true, addEventListener: jest.fn(), removeEventListener: jest.fn() };
  const originalMatchMedia = window.matchMedia;
  window.matchMedia = jest.fn(() => media);
  localStorage.clear();

  render(<ThemeProvider><ThemeHarness /></ThemeProvider>);
  expect(screen.getByText('system:dark')).toBeInTheDocument();
  expect(document.documentElement.dataset.theme).toBe('dark');

  media.matches = false;
  act(() => media.addEventListener.mock.calls[0][1]());
  expect(screen.getByText('system:light')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /use light/i }));
  expect(document.documentElement.dataset.themePreference).toBe('light');
  expect(localStorage.getItem('flowforge:theme')).toBe('light');

  window.matchMedia = originalMatchMedia;
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.removeAttribute('data-theme-preference');
});
