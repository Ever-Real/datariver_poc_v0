import assert from 'node:assert/strict'
import { cp, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { patchCytoscapeSource, run, verifyExternalCss } from './patch-cytoscape-csp.mjs'

const frontendRoot = path.resolve(import.meta.dirname, '..')
const installedPackageRoot = path.join(frontendRoot, 'node_modules/cytoscape')
const cssPath = path.join(frontendRoot, 'src/components/graph/CytoscapeReadGraph.css')

async function withPackageCopy(callback) {
  const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'datariver-cytoscape-csp-'))
  const packageRoot = path.join(temporaryRoot, 'cytoscape')
  await cp(installedPackageRoot, packageRoot, { recursive: true })
  try {
    await callback(packageRoot)
  } finally {
    await rm(temporaryRoot, { recursive: true, force: true })
  }
}

test('patch is version-locked, idempotent, and leaves installed dependency untouched', async () => {
  const installedBefore = await readFile(path.join(installedPackageRoot, 'dist/cytoscape.esm.mjs'), 'utf8')
  await withPackageCopy(async (packageRoot) => {
    const first = await run({ packageRoot, cssPath })
    const second = await run({ packageRoot, cssPath })
    assert.equal(first.digest, second.digest)
    await run({ mode: 'verify', packageRoot, cssPath })
  })
  assert.equal(await readFile(path.join(installedPackageRoot, 'dist/cytoscape.esm.mjs'), 'utf8'), installedBefore)
})

test('patch rejects an unexpected package version', async () => {
  await withPackageCopy(async (packageRoot) => {
    const packagePath = path.join(packageRoot, 'package.json')
    const packageJson = JSON.parse(await readFile(packagePath, 'utf8'))
    packageJson.version = '3.34.2'
    await writeFile(packagePath, `${JSON.stringify(packageJson)}\n`, 'utf8')
    await assert.rejects(run({ packageRoot, cssPath }), /CYTOSCAPE_CSP_UNSUPPORTED_VERSION/)
  })
})

test('patch rejects an unexpected browser entrypoint', async () => {
  await withPackageCopy(async (packageRoot) => {
    const packagePath = path.join(packageRoot, 'package.json')
    const packageJson = JSON.parse(await readFile(packagePath, 'utf8'))
    packageJson.exports['.'].import = './dist/cytoscape.esm.min.mjs'
    await writeFile(packagePath, `${JSON.stringify(packageJson)}\n`, 'utf8')
    await assert.rejects(run({ packageRoot, cssPath }), /CYTOSCAPE_CSP_UNSUPPORTED_BROWSER_ENTRYPOINT/)
  })
})

test('patch rejects unknown source instead of applying a partial compatibility rewrite', async () => {
  await withPackageCopy(async (packageRoot) => {
    const sourcePath = path.join(packageRoot, 'dist/cytoscape.esm.mjs')
    await writeFile(sourcePath, `${await readFile(sourcePath, 'utf8')}\n// unexpected source`, 'utf8')
    await assert.rejects(run({ packageRoot, cssPath }), /CYTOSCAPE_CSP_UNSUPPORTED_SOURCE/)
  })
})

test('source transformer covers stylesheet injection, connected host, layers, dynamic sizing, and detached buffers', async () => {
  const source = await readFile(path.join(installedPackageRoot, 'dist/cytoscape.esm.mjs'), 'utf8')
  const patched = source.includes('cytoscape-csp-canvas-container') ? source : patchCytoscapeSource(source)
  assert.match(patched, /cytoscape-csp-canvas-container/)
  assert.doesNotMatch(patched, /document\.createElement\(['"]style['"]\)/)
  assert.doesNotMatch(patched, /__________cytoscape_stylesheet/)
  assert.doesNotMatch(patched, /canvasContainer\.style/)
  assert.doesNotMatch(patched, /container\.style\[tapHlOffAttr\]/)
  assert.doesNotMatch(patched, /canvas\.style\[/)
  assert.doesNotMatch(patched, /canvas\.style\.(?:position|zIndex|visibility|width|height)/)
  assert.doesNotMatch(patched, /bufferCanvases\[[^\]]+\]\.style/)
  assert.doesNotMatch(patched, /buffCanvas\.style/)
  assert.match(patched, /canvas\.width = canvasWidth/)
  assert.match(patched, /canvas\.height = canvasHeight/)
})

test('external CSS is fail-closed when a required renderer rule is absent', async () => {
  const css = await readFile(cssPath, 'utf8')
  verifyExternalCss(css)
  assert.throws(() => verifyExternalCss(css.replace('canvas[data-id^="layer3"]', 'canvas[data-id^="other"]')), /CYTOSCAPE_CSP_EXTERNAL_CSS_MISSING/)
})

test('missing external presentation rule fails before dependency source mutation', async () => {
  await withPackageCopy(async (packageRoot) => {
    const sourcePath = path.join(packageRoot, 'dist/cytoscape.esm.mjs')
    const invalidCssPath = path.join(packageRoot, 'invalid.css')
    const sourceBefore = await readFile(sourcePath, 'utf8')
    await writeFile(invalidCssPath, '.cy-read-graph-canvas-host {}\n', 'utf8')
    await assert.rejects(run({ packageRoot, cssPath: invalidCssPath }), /CYTOSCAPE_CSP_EXTERNAL_CSS_MISSING/)
    assert.equal(await readFile(sourcePath, 'utf8'), sourceBefore)
  })
})
