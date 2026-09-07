// Shared by the two sequential operational runners. This only budgets read-only polling.
import { AsyncLocalStorage } from 'node:async_hooks'
const budgets = new AsyncLocalStorage()

export function withReadinessDeadline(deadline, operation) {
  return budgets.run(deadline, operation)
}

export function requestBudget(maximumMs = 300_000) {
  const deadline = budgets.getStore()
  return deadline === undefined ? maximumMs : Math.max(1, Math.min(maximumMs, deadline - Date.now()))
}

export function retryAllowed(error) {
  if (error?.terminal) return false
  const status = error?.status
  if (Number.isInteger(status) && status >= 400 && status < 500 && ![408, 429].includes(status)) return false
  const code = error?.classification || error?.message || ''
  if (/NOT_CONFIGURED|CONTRACT|SCHEMA|CONFIG_INVALID|AUTH|FORBIDDEN/.test(code)) return false
  return error?.retryable === true || /_NOT_READY$/.test(code)
}
