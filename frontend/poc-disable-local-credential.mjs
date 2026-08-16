import process from 'node:process'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { normalizePocUsername } from './poc-local-auth.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

const CONFIRMATION = 'DISABLE_LOCAL_CREDENTIAL_AND_REVOKE_SESSIONS'

function cliError(message, code = 'CREDENTIAL_DISABLE_INPUT_INVALID') {
  return Object.assign(new Error(message), { code })
}

export function parseCredentialDisableArguments(argv) {
  const parsed = {}
  const options = new Set(['--env-file', '--username', '--expected-version', '--confirm'])
  for (let index = 0; index < argv.length; index += 1) {
    const option = argv[index]
    if (option === '--help') return { help: true }
    if (!options.has(option)) throw cliError(`Unknown option ${option}.`)
    const value = argv[index + 1]
    if (typeof value !== 'string' || value.startsWith('--')) throw cliError(`${option} requires one value.`)
    index += 1
    const field = {
      '--env-file': 'environmentFile',
      '--username': 'username',
      '--expected-version': 'expectedVersion',
      '--confirm': 'confirmation',
    }[option]
    if (parsed[field] !== undefined) throw cliError(`${option} may be supplied only once.`)
    parsed[field] = value
  }
  for (const [field, option] of [
    ['environmentFile', '--env-file'], ['username', '--username'],
    ['expectedVersion', '--expected-version'], ['confirmation', '--confirm'],
  ]) {
    if (parsed[field] === undefined) throw cliError(`${option} is required.`)
  }
  const expectedVersion = Number(parsed.expectedVersion)
  if (!Number.isSafeInteger(expectedVersion) || expectedVersion < 1) {
    throw cliError('--expected-version must be a positive integer.')
  }
  if (parsed.confirmation !== CONFIRMATION) {
    throw cliError(`--confirm must equal ${CONFIRMATION}.`)
  }
  return {
    environmentFile: resolve(parsed.environmentFile),
    username: normalizePocUsername(parsed.username),
    expectedVersion,
  }
}

export async function disableLocalCredential({
  stateStore, username, expectedVersion, now = () => new Date(), allowInMemoryStoreForTests = false,
}) {
  if ((!stateStore?.configured?.postgres && !allowInMemoryStoreForTests)
    || typeof stateStore?.disableLocalCredential !== 'function') {
    throw cliError('Credential disable requires the configured PostgreSQL state store.', 'CREDENTIAL_DISABLE_STORE_REQUIRED')
  }
  const disabledAt = now().toISOString()
  const result = await stateStore.disableLocalCredential({
    usernameNormalized: normalizePocUsername(username), expectedVersion, disabledAt,
  })
  if (!result) throw cliError('The local credential was not found.', 'CREDENTIAL_NOT_FOUND')
  return {
    subject_id: result.subjectId,
    credential_version: result.credentialVersion,
    login_enabled: result.loginEnabled,
    revoked_session_count: result.revokedSessionCount,
    disabled_at: disabledAt,
  }
}

function usage() {
  return `Usage: node poc-disable-local-credential.mjs --env-file <path> --username <name> --expected-version <n> --confirm ${CONFIRMATION}\n`
}

async function main() {
  const parsed = parseCredentialDisableArguments(process.argv.slice(2))
  if (parsed.help) {
    process.stdout.write(usage())
    return
  }
  process.loadEnvFile(parsed.environmentFile)
  const stateStore = createPocStateStore()
  try {
    const result = await disableLocalCredential({
      stateStore, username: parsed.username, expectedVersion: parsed.expectedVersion,
    })
    process.stdout.write(`${JSON.stringify(result)}\n`)
  } finally {
    await stateStore.close()
  }
}

if (resolve(process.argv[1] || '') === resolve(fileURLToPath(import.meta.url))) {
  main().catch((error) => {
    process.stderr.write(`${error?.code || 'CREDENTIAL_DISABLE_FAILED'}: ${error instanceof Error ? error.message : String(error)}\n`)
    process.exitCode = 1
  })
}
