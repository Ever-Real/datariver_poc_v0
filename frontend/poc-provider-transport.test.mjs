import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { createServer as createHttpServer } from 'node:http'
import { createServer as createHttpsServer } from 'node:https'
import net from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import test from 'node:test'

import { compileNoProxy, createProviderTransport } from './poc-provider-transport.mjs'

async function listen(server) {
  await new Promise((resolvePromise) => server.listen(0, '127.0.0.1', resolvePromise))
  const address = server.address()
  assert(address && typeof address === 'object')
  return address.port
}

async function close(server) {
  await new Promise((resolvePromise) => server.close(resolvePromise))
}

function targetServer() {
  return createHttpServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end('{"status":"PASS"}')
  })
}

function connectProxy(observed) {
  const proxy = createHttpServer((_request, response) => {
    response.writeHead(501)
    response.end()
  })
  proxy.on('connect', (request, client, head) => {
    observed.push(request.url)
    const separator = request.url.lastIndexOf(':')
    const host = request.url.slice(0, separator)
    const port = Number(request.url.slice(separator + 1))
    const upstream = net.connect(port, host, () => {
      client.write('HTTP/1.1 200 Connection Established\r\n\r\n')
      if (head.length) upstream.write(head)
      upstream.pipe(client)
      client.pipe(upstream)
    })
    upstream.on('error', () => client.destroy())
  })
  return proxy
}

test('NO_PROXY supports exact host, suffix, IPv4, IPv6 and optional port', () => {
  const bypass = compileNoProxy('localhost,.corp.example,127.0.0.1:8080,[::1]:8443')
  assert.equal(bypass('http://localhost:1234'), true)
  assert.equal(bypass('https://api.corp.example'), true)
  assert.equal(bypass('http://127.0.0.1:8080'), true)
  assert.equal(bypass('http://127.0.0.1:8081'), false)
  assert.equal(bypass('https://[::1]:8443'), true)
  assert.equal(bypass('https://public.example'), false)
})

test('build proxy variables alone never route Product provider traffic', async () => {
  const target = targetServer()
  const targetPort = await listen(target)
  const observed = []
  const proxy = connectProxy(observed)
  const proxyPort = await listen(proxy)
  const transport = createProviderTransport({
    HTTP_PROXY: `http://127.0.0.1:${proxyPort}`,
    HTTPS_PROXY: `http://127.0.0.1:${proxyPort}`,
  })
  try {
    const response = await transport.fetch(`http://127.0.0.1:${targetPort}/direct`)
    assert.equal(response.status, 200)
    assert.equal(transport.route(`http://127.0.0.1:${targetPort}/direct`), 'DIRECT')
    assert.deepEqual(observed, [])
  } finally {
    await transport.close()
    await close(proxy)
    await close(target)
  }
})

test('runtime proxy and runtime NO_PROXY use one explicit transport policy', async () => {
  const target = targetServer()
  const targetPort = await listen(target)
  const observed = []
  const proxy = connectProxy(observed)
  const proxyPort = await listen(proxy)
  const proxied = createProviderTransport({
    POC_RUNTIME_HTTP_PROXY: `http://127.0.0.1:${proxyPort}`,
  })
  const bypassed = createProviderTransport({
    POC_RUNTIME_HTTP_PROXY: `http://127.0.0.1:${proxyPort}`,
    POC_RUNTIME_NO_PROXY: '127.0.0.1',
  })
  try {
    assert.equal((await proxied.fetch(`http://127.0.0.1:${targetPort}/proxy`)).status, 200)
    assert.equal(proxied.route(`http://127.0.0.1:${targetPort}/proxy`), 'PROXY')
    assert.equal(observed.length, 1)
    assert.equal((await bypassed.fetch(`http://127.0.0.1:${targetPort}/direct`)).status, 200)
    assert.equal(bypassed.route(`http://127.0.0.1:${targetPort}/direct`), 'DIRECT')
    assert.equal(observed.length, 1)
  } finally {
    await proxied.close()
    await bypassed.close()
    await close(proxy)
    await close(target)
  }
})

test('target-local private CA enables HTTPS without disabling TLS verification', async (context) => {
  const directory = await mkdtemp(join(tmpdir(), 'datariver-provider-ca-'))
  const key = join(directory, 'key.pem')
  const certificate = join(directory, 'certificate.pem')
  const generated = spawnSync('openssl', [
    'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
    '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
    '-keyout', key, '-out', certificate,
  ], { stdio: 'ignore' })
  if (generated.status !== 0) {
    await rm(directory, { recursive: true, force: true })
    context.skip('openssl is unavailable')
    return
  }
  const server = createHttpsServer({
    key: await readFile(key),
    cert: await readFile(certificate),
  }, (_request, response) => {
    response.writeHead(200)
    response.end('ok')
  })
  const port = await listen(server)
  const rejected = createProviderTransport({})
  const trusted = createProviderTransport({ POC_RUNTIME_CA_CERT_FILE: certificate })
  try {
    await assert.rejects(rejected.fetch(`https://localhost:${port}/provider`))
    assert.equal((await trusted.fetch(`https://localhost:${port}/provider`)).status, 200)
  } finally {
    await rejected.close()
    await trusted.close()
    await close(server)
    await rm(directory, { recursive: true, force: true })
  }
})
