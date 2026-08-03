import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from 'axios';

import { runtimeConfig } from '../config';
import { normalizeApiError } from './api-error';

export type RequestConfig<TData = unknown> = AxiosRequestConfig<TData>;
export type RequestClient = AxiosInstance;

export function createRequestClient(config: AxiosRequestConfig = {}): AxiosInstance {
  return axios.create({
    baseURL: runtimeConfig.api.baseUrl,
    timeout: runtimeConfig.api.timeoutMs,
    ...config,
  });
}

export function createRequest(client: AxiosInstance) {
  return async function request<TResponse = unknown, TData = unknown>(
    config: RequestConfig<TData>,
  ): Promise<TResponse> {
    try {
      const response = await client.request<TResponse, AxiosResponse<TResponse>, TData>(config);
      return response.data;
    } catch (error) {
      throw normalizeApiError(error);
    }
  };
}

export const requestClient = createRequestClient();

export const request = createRequest(requestClient);

export type { AxiosError, AxiosRequestConfig, AxiosResponse } from 'axios';
