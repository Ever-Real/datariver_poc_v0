import { configDefaults, defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    pool: 'threads',
    maxWorkers: 2,
    exclude: [...configDefaults.exclude, 'poc-server*.test.mjs', 'chat-router-benchmark.test.mjs'],
  },
})
