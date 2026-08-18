import { configDefaults, defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    pool: 'threads',
    // The full jsdom suite contains real lazy-route and graph navigation
    // tests. Two file workers contend on transforms and event-loop time on
    // the supported DEV runner, producing false 1 s/5 s navigation timeouts.
    maxWorkers: 1,
    exclude: [...configDefaults.exclude, '**/*.test.mjs'],
  },
})
