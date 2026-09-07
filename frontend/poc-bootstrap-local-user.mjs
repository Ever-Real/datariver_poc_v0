/* global Buffer */
import { constants as fileConstants } from 'node:fs'
import { lstat, open } from 'node:fs/promises'
import process from 'node:process'
import { emitKeypressEvents } from 'node:readline'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

import {
  CHANGE_HISTORY_ACCESS_ROLES,
  CHANGE_HISTORY_RESPONSIBILITIES,
  changeHistoryAccessCoreProjection,
  changeHistoryDocumentFromSnapshot,
  normalizeChangeHistoryAccessDocument,
  privateChangeHistoryAccess,
} from './poc-access-document.mjs'
import { hashPocPassword, normalizePocUsername } from './poc-local-auth.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

const maximumPasswordFileBytes = 1026

function cliError(message, code = 'BOOTSTRAP_INPUT_INVALID') {
  return Object.assign(new Error(message), { code })
}

function takeValue(argv, index, option) {
  const value = argv[index + 1]
  if (typeof value !== 'string' || value.startsWith('--')) {
    throw cliError(`${option} requires one value.`)
  }
  return value
}

function parseSystemAssignment(raw) {
  const parts = raw.split(':')
  if (parts.length !== 3) {
    throw cliError('--system-assignment requires <system-id>:<responsibility>:<positive-priority>.')
  }
  const [systemId, responsibility, rawPriority] = parts
  const priority = Number(rawPriority)
  if (!systemId || !CHANGE_HISTORY_RESPONSIBILITIES.includes(responsibility)
    || !Number.isSafeInteger(priority) || priority < 1) {
    throw cliError('--system-assignment is outside its canonical contract.')
  }
  return { systemId, responsibility, priority }
}

function normalizeStableSubjectId(value) {
  if (typeof value !== 'string' || value.trim() !== value || value.length < 1 || value.length > 255
    || [...value].some((character) => {
      const codePoint = character.codePointAt(0)
      return codePoint <= 0x1f || codePoint === 0x7f
    })) {
    throw cliError('--subject-id is outside its stable bounded contract.')
  }
  return value
}

export function parseLocalHumanBootstrapArguments(argv) {
  const parsed = { assignments: [], mustChangePassword: false, setActiveSubject: false }
  const values = new Set([
    '--env-file', '--password-file', '--subject-id', '--username', '--role', '--system-assignment',
  ])
  for (let index = 0; index < argv.length; index += 1) {
    const option = argv[index]
    if (option === '--help') return { help: true }
    if (option === '--set-active-subject') {
      if (parsed.setActiveSubject) throw cliError('--set-active-subject may be supplied only once.')
      parsed.setActiveSubject = true
      continue
    }
    if (option === '--must-change-password') {
      if (parsed.mustChangePassword) throw cliError('--must-change-password may be supplied only once.')
      parsed.mustChangePassword = true
      continue
    }
    if (!values.has(option)) {
      throw cliError(typeof option === 'string' && option.startsWith('--password=')
        ? 'Password values are forbidden in arguments; use the TTY prompt or --password-file.'
        : `Unknown option ${option}.`)
    }
    const value = takeValue(argv, index, option)
    index += 1
    if (option === '--system-assignment') {
      parsed.assignments.push(parseSystemAssignment(value))
      continue
    }
    const field = {
      '--env-file': 'environmentFile',
      '--password-file': 'passwordFile',
      '--subject-id': 'subjectId',
      '--username': 'username',
      '--role': 'role',
    }[option]
    if (parsed[field] !== undefined) throw cliError(`${option} may be supplied only once.`)
    parsed[field] = value
  }
  for (const [field, option] of [
    ['subjectId', '--subject-id'], ['username', '--username'], ['role', '--role'],
  ]) {
    if (parsed[field] === undefined) throw cliError(`${option} is required.`)
  }
  if (!CHANGE_HISTORY_ACCESS_ROLES.includes(parsed.role)) {
    throw cliError('--role must be one canonical local human role.')
  }
  parsed.subjectId = normalizeStableSubjectId(parsed.subjectId)
  parsed.username = normalizePocUsername(parsed.username)
  return parsed
}

function initialAccessDocument(snapshot, subjectId) {
  const core = snapshot.core.value && typeof snapshot.core.value === 'object' && !Array.isArray(snapshot.core.value)
    ? snapshot.core.value
    : {}
  const groupedScopes = Array.isArray(core.adminSystemSchemaScopes) ? core.adminSystemSchemaScopes : []
  return {
    schema_version: 1,
    active_subject_id: subjectId,
    users: [],
    systems: Array.isArray(core.adminSystems) ? core.adminSystems : [],
    system_schema_scopes: groupedScopes.flatMap((entry) => Array.isArray(entry?.[1]) ? entry[1] : []),
    system_assignments: [],
  }
}

export async function bootstrapLocalHumanAccount({
  stateStore,
  subjectId,
  username,
  role,
  password,
  assignments = [],
  mustChangePassword = false,
  setActiveSubject = false,
}) {
  if (!stateStore || typeof stateStore.readChangeHistoryAccess !== 'function'
    || typeof stateStore.readLocalCredential !== 'function'
    || typeof stateStore.provisionLocalCredential !== 'function') {
    throw cliError('The local account bootstrap state store is unavailable.', 'BOOTSTRAP_STORE_UNAVAILABLE')
  }
  if (!CHANGE_HISTORY_ACCESS_ROLES.includes(role)) {
    throw cliError('The requested role is not canonical.')
  }
  const expectedResponsibility = role === 'developer'
    ? 'DEVELOPER'
    : role === 'data_steward'
      ? 'DATA_STEWARD'
      : role === 'manager' ? 'MANAGER' : null
  if (assignments.some((assignment) => assignment.responsibility !== expectedResponsibility)) {
    throw cliError('Responsible System assignments must match the user role.', 'ASSIGNMENT_ROLE_MISMATCH')
  }
  const normalizedSubjectId = normalizeStableSubjectId(subjectId)
  const usernameNormalized = normalizePocUsername(username)
  const snapshot = await stateStore.readChangeHistoryAccess()
  const currentDocument = snapshot.access.value === null
    ? initialAccessDocument(snapshot, normalizedSubjectId)
    : changeHistoryDocumentFromSnapshot(snapshot)
  if (currentDocument.users.some((user) => user.subject_id === normalizedSubjectId)) {
    throw cliError('The local access subject already exists.', 'SUBJECT_EXISTS')
  }
  if (await stateStore.readLocalCredential(usernameNormalized)) {
    throw cliError('The local credential subject or username already exists.', 'CREDENTIAL_EXISTS')
  }
  const newUser = {
    subject_id: normalizedSubjectId,
    username: usernameNormalized,
    role,
    active: true,
    max_security_grade: 'normal',
    provider_owner_refs: [],
  }
  const document = normalizeChangeHistoryAccessDocument({
    ...currentDocument,
    active_subject_id: snapshot.access.value === null || setActiveSubject
      ? normalizedSubjectId
      : currentDocument.active_subject_id,
    users: [...currentDocument.users, newUser],
    system_assignments: [
      ...currentDocument.system_assignments,
      ...assignments.map((assignment) => ({
        system_id: assignment.systemId,
        subject_id: normalizedSubjectId,
        responsibility: assignment.responsibility,
        priority: assignment.priority,
        active: true,
      })),
    ],
  }, {
    allowUnresolvedActiveSubject: snapshot.access.value !== null && !setActiveSubject,
  })
  const passwordHash = await hashPocPassword(password)
  const result = await stateStore.provisionLocalCredential({
    expectedAccessVersion: snapshot.access.version,
    expectedCoreVersion: snapshot.core.version,
    accessValue: privateChangeHistoryAccess(document),
    coreValue: changeHistoryAccessCoreProjection(
      snapshot.core.value,
      document,
      snapshot.access.version + 1,
    ),
    credential: {
      subjectId: normalizedSubjectId,
      usernameNormalized,
      passwordHash,
      loginEnabled: true,
      mustChangePassword,
    },
  })
  return {
    subjectId: normalizedSubjectId,
    username: usernameNormalized,
    role,
    mustChangePassword,
    activeSubjectId: document.active_subject_id,
    assignmentCount: assignments.length,
    ...result,
  }
}

export async function readBootstrapPasswordFile(path) {
  const metadata = await lstat(path)
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > maximumPasswordFileBytes) {
    throw cliError('The password file must be one bounded regular file.')
  }
  const noFollow = fileConstants.O_NOFOLLOW ?? 0
  const handle = await open(path, fileConstants.O_RDONLY | noFollow)
  try {
    const value = await handle.readFile({ encoding: 'utf8' })
    const password = value.endsWith('\r\n') ? value.slice(0, -2)
      : value.endsWith('\n') ? value.slice(0, -1)
        : value
    if (!password || /[\r\n\0]/.test(password)) {
      throw cliError('The password file must contain exactly one non-empty password line.')
    }
    return password
  } finally {
    await handle.close()
  }
}

function hiddenLine(prompt, input, output) {
  if (!input.isTTY || !output.isTTY || typeof input.setRawMode !== 'function') {
    throw cliError('A TTY is required when --password-file is not supplied.', 'BOOTSTRAP_TTY_REQUIRED')
  }
  emitKeypressEvents(input)
  return new Promise((resolvePromise, reject) => {
    const wasRaw = input.isRaw
    let value = ''
    const cleanup = () => {
      input.off('keypress', onKeypress)
      input.setRawMode(wasRaw)
      output.write('\n')
    }
    const onKeypress = (text, key = {}) => {
      if (key.ctrl && key.name === 'c') {
        cleanup()
        reject(cliError('Password entry was cancelled.', 'BOOTSTRAP_CANCELLED'))
        return
      }
      if (key.name === 'return' || key.name === 'enter') {
        cleanup()
        resolvePromise(value)
        return
      }
      if (key.name === 'backspace') {
        value = [...value].slice(0, -1).join('')
        return
      }
      if (!key.ctrl && !key.meta && typeof text === 'string' && !/[\r\n\0]/.test(text)) {
        value += text
        if (Buffer.byteLength(value, 'utf8') > 1024) {
          cleanup()
          reject(cliError('Password entry exceeds its bounded contract.'))
        }
      }
    }
    output.write(prompt)
    input.setRawMode(true)
    input.resume()
    input.on('keypress', onKeypress)
  })
}

export async function readBootstrapPasswordFromTty(input = process.stdin, output = process.stderr) {
  const password = await hiddenLine('Password: ', input, output)
  const confirmation = await hiddenLine('Confirm password: ', input, output)
  if (password !== confirmation) throw cliError('Password confirmation did not match.')
  return password
}

export function localHumanBootstrapHelp() {
  return [
    'Usage: npm run poc:bootstrap-user -- --subject-id <stable-subject-id> --username <normalized-username> --role <admin|data_steward|developer|manager|viewer> [options]',
    '',
    'Options:',
    '  --password-file <path>  Read the human password from one bounded file instead of the TTY.',
    '  --env-file <path>       Load the local POC database configuration file.',
    '  --system-assignment <system-id>:<DATA_STEWARD|DEVELOPER|MANAGER>:<positive-priority>',
    '                           Add one active System assignment; repeat for more.',
    '  --must-change-password   Mark the new credential for a required password change.',
    '  --set-active-subject     Explicitly replace active_subject_id with the new subject.',
  ].join('\n')
}

export async function runLocalHumanBootstrapCli(argv, {
  stateStore: suppliedStateStore,
  input = process.stdin,
  output = process.stdout,
  errorOutput = process.stderr,
  loadEnvironmentFile = (path) => process.loadEnvFile(path),
  passwordFileReader = readBootstrapPasswordFile,
  stateStoreFactory = createPocStateStore,
  ttyPasswordReader = readBootstrapPasswordFromTty,
} = {}) {
  const options = parseLocalHumanBootstrapArguments(argv)
  if (options.help) {
    output.write(`${localHumanBootstrapHelp()}\n`)
    return undefined
  }
  if (!suppliedStateStore && options.environmentFile) loadEnvironmentFile(resolve(options.environmentFile))
  const stateStore = suppliedStateStore ?? stateStoreFactory()
  if (!suppliedStateStore && !stateStore.configured.postgres) {
    throw cliError('The operator bootstrap requires configured PostgreSQL storage.', 'BOOTSTRAP_POSTGRES_REQUIRED')
  }
  try {
    const password = options.passwordFile
      ? await passwordFileReader(resolve(options.passwordFile))
      : await ttyPasswordReader(input, errorOutput)
    const result = await bootstrapLocalHumanAccount({
      stateStore,
      subjectId: options.subjectId,
      username: options.username,
      role: options.role,
      password,
      assignments: options.assignments,
      mustChangePassword: options.mustChangePassword,
      setActiveSubject: options.setActiveSubject,
    })
    output.write(`${JSON.stringify({
      status: 'created',
      subject_id: result.subjectId,
      username: result.username,
      role: result.role,
      must_change_password: result.mustChangePassword,
      active_subject_id: result.activeSubjectId,
      system_assignment_count: result.assignmentCount,
      access_version: result.accessVersion,
      core_version: result.coreVersion,
      credential_version: result.credentialVersion,
    })}\n`)
    return result
  } finally {
    await stateStore.close?.()
  }
}

if (resolve(process.argv[1] || '') === resolve(fileURLToPath(import.meta.url))) {
  runLocalHumanBootstrapCli(process.argv.slice(2)).catch((error) => {
    const code = typeof error?.code === 'string' ? error.code : 'BOOTSTRAP_FAILED'
    process.stderr.write(`${code}: ${error instanceof Error ? error.message : 'Local account bootstrap failed.'}\n`)
    process.exitCode = 1
  })
}
