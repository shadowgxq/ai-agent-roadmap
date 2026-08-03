import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';
import prettierConfig from 'eslint-config-prettier';

function restrictImportsFrom(layers) {
  return [
    'error',
    {
      patterns: [
        {
          group: layers.map((layer) => `**/${layer}/**`),
          message:
            'Import direction must follow app -> pages -> widgets -> features -> entities -> shared.',
        },
      ],
    },
  ];
}

export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      '.git/**',
      '.codex/**',
      '.agents/**',
      'openspec/changes/**',
      '**/*.incoming*',
    ],
  },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },
  {
    files: ['src/shared/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': restrictImportsFrom([
        'app',
        'pages',
        'widgets',
        'features',
        'entities',
      ]),
    },
  },
  {
    files: ['src/entities/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': restrictImportsFrom(['app', 'pages', 'widgets', 'features']),
    },
  },
  {
    files: ['src/features/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': restrictImportsFrom(['app', 'pages', 'widgets']),
    },
  },
  {
    files: ['src/widgets/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': restrictImportsFrom(['app', 'pages']),
    },
  },
  {
    files: ['src/pages/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': restrictImportsFrom(['app']),
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/shared/config/**'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "MemberExpression[object.type='MetaProperty'][property.name='env']",
          message: 'Read import.meta.env only in shared/config and expose typed runtime config.',
        },
      ],
    },
  },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['vite.config.ts', 'scripts/**/*.ts'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.node,
    },
  },
  {
    extends: [js.configs.recommended],
    files: ['scripts/**/*.{js,mjs,cjs}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.node,
    },
  },
  prettierConfig,
);
