import { getWorkIntelligenceBriefing } from './intelligenceService';

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ engine: 'deterministic', recommendations: [] }),
  });
});

afterEach(() => jest.restoreAllMocks());

test('loads the current user permission-filtered briefing', async () => {
  await expect(getWorkIntelligenceBriefing()).resolves.toEqual({
    engine: 'deterministic', recommendations: [],
  });
  expect(global.fetch).toHaveBeenCalledWith(
    expect.stringMatching(/\/api\/v1\/intelligence\/briefing$/),
    { credentials: 'include' },
  );
});
