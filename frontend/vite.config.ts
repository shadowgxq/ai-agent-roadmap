import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { loadEnv, type ProxyOptions } from 'vite';

const vendorChunkGroups = [
  {
    name: 'framework',
    packages: [
      'react',
      'react-dom',
      'react-router',
      'react-router-dom',
      '@remix-run/router',
      'scheduler',
    ],
  },
  {
    name: 'data',
    packages: ['@tanstack/react-query', '@tanstack/query-core', 'axios', 'zustand'],
  },
  {
    name: 'ui',
    packages: ['@radix-ui/', 'lucide-react'],
  },
  {
    name: 'i18n',
    packages: ['i18next', 'react-i18next'],
  },
] as const;

const DEFAULT_DEV_SERVER_PORT = 5173;
const DEFAULT_PROXY_PREFIX = '/api';

function matchesPackage(id: string, packageName: string) {
  const packagePath = `/node_modules/${packageName}`;

  if (packageName.endsWith('/')) {
    return id.includes(packagePath);
  }

  return id.includes(`${packagePath}/`) || id.endsWith(packagePath);
}

function manualChunks(id: string) {
  const normalizedId = id.split('\\').join('/');

  if (!normalizedId.includes('/node_modules/')) {
    return undefined;
  }

  const chunkGroup = vendorChunkGroups.find((group) =>
    group.packages.some((packageName) => matchesPackage(normalizedId, packageName)),
  );

  return chunkGroup?.name;
}

function readPositiveInteger(value: string | undefined, fallback: number) {
  const parsedValue = Number(value);
  return Number.isInteger(parsedValue) && parsedValue > 0 ? parsedValue : fallback;
}

function createServerProxy(env: Record<string, string>): Record<string, ProxyOptions> | undefined {
  const target = env.DEV_PROXY_TARGET?.trim();

  if (!target) {
    return undefined;
  }

  let proxyUrl: URL;
  try {
    proxyUrl = new URL(target);
  } catch {
    throw new Error('DEV_PROXY_TARGET must be a valid absolute URL.');
  }

  if (!['http:', 'https:'].includes(proxyUrl.protocol)) {
    throw new Error('DEV_PROXY_TARGET must use the http or https protocol.');
  }

  const prefix = env.DEV_PROXY_PREFIX?.trim() || DEFAULT_PROXY_PREFIX;
  if (!prefix.startsWith('/')) {
    throw new Error('DEV_PROXY_PREFIX must start with /.');
  }

  return {
    [prefix]: {
      target: proxyUrl.toString().replace(/\/$/, ''),
      changeOrigin: true,
      secure: env.DEV_PROXY_SECURE?.toLowerCase() !== 'false',
      rewrite: (path) => path.slice(prefix.length) || '/',
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');

  return {
    plugins: [react()],
    resolve: {
      dedupe: ['react', 'react-dom'],
    },
    server: {
      port: readPositiveInteger(env.DEV_SERVER_PORT, DEFAULT_DEV_SERVER_PORT),
      proxy: createServerProxy(env),
    },
    build: {
      target: 'es2022',
      sourcemap: env.BUILD_SOURCEMAP === 'true',
      chunkSizeWarningLimit: 700,
      rollupOptions: {
        output: {
          manualChunks,
        },
      },
    },
    optimizeDeps: {
      include: [
        'react',
        'react-dom/client',
        'react-router-dom',
        '@tanstack/react-query',
        'axios',
        'zustand',
        'lucide-react',
        'i18next',
        'react-i18next',
      ],
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/shared/testing/setupTests.ts',
      clearMocks: true,
      restoreMocks: true,
    },
  };
});
