import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { isIP } from 'node:net'
import process from 'node:process'
import { URL } from 'node:url'

import { Agent, ProxyAgent, fetch as undiciFetch } from 'undici'

function optionalUrl(raw, name, { credentials = false } = {}) {
  const normalized = typeof raw === 'string' ? raw.trim() : ''
  if (!normalized) return undefined
  const value = new URL(normalized)
  if (!['http:', 'https:'].includes(value.protocol) || value.hash
    || (!credentials && (value.username || value.password))) {
    throw new Error(`${name} must be an HTTP(S) URL${credentials ? '' : ' without credentials'} and no fragment.`)
  }
  return value.toString()
}

function optionalCa(path) {
  const normalized = typeof path === 'string' ? path.trim() : ''
  if (!normalized) return undefined
  const value = readFileSync(normalized, 'utf8')
  if (!value.trim() || Buffer.byteLength(value) > 1024 * 1024) {
    throw new Error('POC_RUNTIME_CA_CERT_FILE must contain one bounded CA bundle.')
  }
  return value
}

function normalizedHostname(value) {
  const lower = value.trim().toLowerCase()
  return lower.startsWith('[') && lower.endsWith(']') ? lower.slice(1, -1) : lower
}

function noProxyEntry(raw) {
  const value = raw.trim().toLowerCase()
  if (!value) return null
  if (value === '*') return { host: '*', port: null, suffix: false }
  let host = value
  let port = null
  if (value.startsWith('[')) {
    const closing = value.indexOf(']')
    if (closing < 0) throw new Error('POC_RUNTIME_NO_PROXY contains an invalid IPv6 entry.')
    host = value.slice(1, closing)
    const remainder = value.slice(closing + 1)
    if (remainder) {
      if (!/^:\d{1,5}$/.test(remainder)) throw new Error('POC_RUNTIME_NO_PROXY contains an invalid port.')
      port = remainder.slice(1)
    }
  } else if ((value.match(/:/g) || []).length === 1) {
    const separator = value.lastIndexOf(':')
    if (/^\d{1,5}$/.test(value.slice(separator + 1))) {
      host = value.slice(0, separator)
      port = value.slice(separator + 1)
    }
  }
  const suffix = host.startsWith('*.') || host.startsWith('.')
  host = normalizedHostname(host.replace(/^\*\./, '.'))
  if (!host || (!isIP(host) && !/^\.?[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$/.test(host))) {
    throw new Error('POC_RUNTIME_NO_PROXY contains an invalid host entry.')
  }
  const numericPort = port === null ? null : Number(port)
  if (numericPort !== null && (numericPort < 1 || numericPort > 65535)) {
    throw new Error('POC_RUNTIME_NO_PROXY contains an invalid port.')
  }
  return { host, port, suffix }
}

export function compileNoProxy(raw) {
  const entries = String(raw || '').split(/[\s,]+/u).map(noProxyEntry).filter(Boolean)
  return (target) => {
    const url = target instanceof URL ? target : new URL(target)
    const hostname = normalizedHostname(url.hostname)
    const port = url.port || (url.protocol === 'https:' ? '443' : '80')
    return entries.some((entry) => {
      if (entry.port !== null && entry.port !== port) return false
      if (entry.host === '*') return true
      if (entry.suffix) {
        const suffix = entry.host.replace(/^\./, '')
        return hostname === suffix || hostname.endsWith(`.${suffix}`)
      }
      return hostname === entry.host
    })
  }
}

export function runtimeProviderNetwork(environment = process.env) {
  const httpProxy = optionalUrl(environment.POC_RUNTIME_HTTP_PROXY, 'POC_RUNTIME_HTTP_PROXY', { credentials: true })
  const httpsProxy = optionalUrl(environment.POC_RUNTIME_HTTPS_PROXY, 'POC_RUNTIME_HTTPS_PROXY', { credentials: true })
  const noProxy = String(environment.POC_RUNTIME_NO_PROXY || '').trim()
  const ca = optionalCa(environment.POC_RUNTIME_CA_CERT_FILE)
  return Object.freeze({ httpProxy, httpsProxy, noProxy, ca })
}

export function createProviderTransport(environment = process.env) {
  const network = runtimeProviderNetwork(environment)
  const bypass = compileNoProxy(network.noProxy)
  const connect = network.ca ? { ca: network.ca, rejectUnauthorized: true } : undefined
  const direct = new Agent(connect ? { connect } : {})
  const proxies = new Map()
  const proxyFor = (url) => {
    const proxyUrl = url.protocol === 'https:'
      ? (network.httpsProxy || network.httpProxy)
      : network.httpProxy
    if (!proxyUrl || bypass(url)) return null
    if (!proxies.has(proxyUrl)) {
      proxies.set(proxyUrl, new ProxyAgent({
        uri: proxyUrl,
        ...(connect ? { requestTls: connect, proxyTls: connect } : {}),
      }))
    }
    return proxies.get(proxyUrl)
  }
  return Object.freeze({
    route(target) {
      const url = target instanceof URL ? target : new URL(target)
      return proxyFor(url) ? 'PROXY' : 'DIRECT'
    },
    async fetch(target, options = {}) {
      if ('dispatcher' in options) throw new Error('Provider dispatcher overrides are forbidden.')
      const url = target instanceof URL ? target : new URL(target)
      return undiciFetch(url, { ...options, dispatcher: proxyFor(url) || direct })
    },
    async close() {
      await Promise.allSettled([direct.close(), ...[...proxies.values()].map((agent) => agent.close())])
    },
  })
}

export function joinProviderUrl(base, suffix) {
  return `${String(base).replace(/\/$/, '')}/${String(suffix).replace(/^\//, '')}`
}

export function llmEndpoint(provider, endpoint) {
  const requested = `/${String(endpoint).replace(/^\//, '')}`
  const value = new URL(provider.url)
  const knownEndpoints = ['/chat/completions', '/embeddings', '/rerankings', '/rerank', '/models']
  const configuredEndpoint = knownEndpoints.find((candidate) => value.pathname.endsWith(candidate))
  if (configuredEndpoint) {
    if (configuredEndpoint === requested
      || (requested === '/rerank' && configuredEndpoint === '/rerankings')) return value.toString()
    value.pathname = value.pathname.slice(0, -configuredEndpoint.length) || '/'
  }
  return joinProviderUrl(value.toString(), requested)
}
