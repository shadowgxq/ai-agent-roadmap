export const DEFAULT_API_TIMEOUT_MS = 10000;

type RuntimeEnv = {
  VITE_API_BASE_URL?: string;
  VITE_API_TIMEOUT_MS?: string;
};

export type RuntimeConfig = Readonly<{
  api: Readonly<{
    baseUrl?: string;
    timeoutMs: number;
  }>;
}>;

function readOptionalString(value: string | undefined) {
  const normalizedValue = value?.trim();
  return normalizedValue || undefined;
}

function readPositiveNumber(value: string | undefined, fallback: number) {
  const parsedValue = Number(value);
  return Number.isFinite(parsedValue) && parsedValue > 0 ? parsedValue : fallback;
}

export function createRuntimeConfig(env: RuntimeEnv): RuntimeConfig {
  return Object.freeze({
    api: Object.freeze({
      baseUrl: readOptionalString(env.VITE_API_BASE_URL),
      timeoutMs: readPositiveNumber(env.VITE_API_TIMEOUT_MS, DEFAULT_API_TIMEOUT_MS),
    }),
  });
}

export const runtimeConfig = createRuntimeConfig(import.meta.env);
