import axios from 'axios';

const DEFAULT_API_ERROR_MESSAGE = 'Request failed';

export type ApiError = {
  __apiError: true;
  message: string;
  status?: number;
  code?: string | number;
  details?: unknown;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export function isApiError(error: unknown): error is ApiError {
  return isRecord(error) && error.__apiError === true && typeof error.message === 'string';
}

export function normalizeApiError(error: unknown): ApiError {
  if (isApiError(error)) {
    return error;
  }

  if (axios.isAxiosError(error)) {
    const data = isRecord(error.response?.data) ? error.response.data : undefined;
    const message =
      (typeof data?.message === 'string' && data.message) ||
      (typeof data?.msg === 'string' && data.msg) ||
      error.message ||
      DEFAULT_API_ERROR_MESSAGE;
    const code =
      typeof data?.code === 'string' || typeof data?.code === 'number' ? data.code : error.code;

    return {
      __apiError: true,
      message,
      status: error.response?.status,
      code,
      details: data?.details,
    };
  }

  return {
    __apiError: true,
    message: error instanceof Error ? error.message : DEFAULT_API_ERROR_MESSAGE,
  };
}
