import { describe, expect, it } from 'vitest';

import { createRuntimeConfig, DEFAULT_API_TIMEOUT_MS } from './runtime-config';

describe('createRuntimeConfig', () => {
  it('normalizes configured API values', () => {
    expect(
      createRuntimeConfig({
        VITE_API_BASE_URL: ' /api/v2 ',
        VITE_API_TIMEOUT_MS: '15000',
      }),
    ).toEqual({
      api: {
        baseUrl: '/api/v2',
        timeoutMs: 15000,
      },
    });
  });

  it('uses safe defaults for empty or invalid values', () => {
    expect(
      createRuntimeConfig({
        VITE_API_BASE_URL: '  ',
        VITE_API_TIMEOUT_MS: '-1',
      }),
    ).toEqual({
      api: {
        baseUrl: undefined,
        timeoutMs: DEFAULT_API_TIMEOUT_MS,
      },
    });
  });
});
