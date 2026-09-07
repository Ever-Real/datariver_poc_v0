#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const SUPPORTED_VERSION = '3.34.1'
const PRISTINE_SOURCE_SHA256 = '57f306c96a2197421ec438370599278013420f2f03bd29e3b6483b41b157951e'
const PATCHED_SOURCE_SHA256 = '53743530d0f0d8e4abfab39ca99acfa97cfa825f6608b739f1686138e58d8093'

const replacements = [
  {
    name: 'renderer stylesheet injection',
    before: `  // prepend a stylesheet in the head such that
  if (containerWindow) {
    var document = containerWindow.document;
    var head = document.head;
    var stylesheetId = '__________cytoscape_stylesheet';
    var className = '__________cytoscape_container';
    var stylesheetAlreadyExists = document.getElementById(stylesheetId) != null;
    if (ctr.className.indexOf(className) < 0) {
      ctr.className = (ctr.className || '') + ' ' + className;
    }
    if (!stylesheetAlreadyExists) {
      var stylesheet = document.createElement('style');
      stylesheet.id = stylesheetId;
      stylesheet.textContent = '.' + className + ' { position: relative; }';
      head.insertBefore(stylesheet, head.children[0]); // first so lowest priority
    }
    var computedStyle = containerWindow.getComputedStyle(ctr);
    var position = computedStyle.getPropertyValue('position');
    if (position === 'static') {
      warn('A Cytoscape container has style position:static and so can not use UI extensions properly');
    }
  }`,
    after: `  if (containerWindow) {
    var className = '__________cytoscape_container';
    if (ctr.className.indexOf(className) < 0) {
      ctr.className = (ctr.className || '') + ' ' + className;
    }
    var computedStyle = containerWindow.getComputedStyle(ctr);
    var position = computedStyle.getPropertyValue('position');
    if (position === 'static') {
      warn('A Cytoscape container has style position:static and so can not use UI extensions properly');
    }
  }`,
  },
  {
    name: 'renderer DOM presentation',
    before: `  var tapHlOffAttr = '-webkit-tap-highlight-color';
  var tapHlOffStyle = 'rgba(0,0,0,0)';
  r.data.canvasContainer = document.createElement('div'); // eslint-disable-line no-undef
  var containerStyle = r.data.canvasContainer.style;
  r.data.canvasContainer.style[tapHlOffAttr] = tapHlOffStyle;
  containerStyle.position = 'relative';
  containerStyle.zIndex = '0';
  containerStyle.overflow = 'hidden';
  var container = options.cy.container();
  container.appendChild(r.data.canvasContainer);
  container.style[tapHlOffAttr] = tapHlOffStyle;
  var styleMap = {
    '-webkit-user-select': 'none',
    '-moz-user-select': '-moz-none',
    'user-select': 'none',
    '-webkit-tap-highlight-color': 'rgba(0,0,0,0)',
    'outline-style': 'none'
  };
  if (ms()) {
    styleMap['-ms-touch-action'] = 'none';
    styleMap['touch-action'] = 'none';
  }`,
    after: `  r.data.canvasContainer = document.createElement('div'); // eslint-disable-line no-undef
  r.data.canvasContainer.className = 'cytoscape-csp-canvas-container';
  var container = options.cy.container();
  container.appendChild(r.data.canvasContainer);`,
  },
  {
    name: 'connected canvas layer presentation',
    before: `    Object.keys(styleMap).forEach(function (k) {
      canvas.style[k] = styleMap[k];
    });
    canvas.style.position = 'absolute';
    canvas.setAttribute('data-id', 'layer' + i);
    canvas.style.zIndex = String(CRp.CANVAS_LAYERS - i);`,
    after: `    canvas.setAttribute('data-id', 'layer' + i);`,
  },
  {
    name: 'detached buffer canvas presentation',
    before: `    r.data.bufferCanvases[i].style.position = 'absolute';
    r.data.bufferCanvases[i].setAttribute('data-id', 'buffer' + i);
    r.data.bufferCanvases[i].style.zIndex = String(-i - 1);
    r.data.bufferCanvases[i].style.visibility = 'hidden';`,
    after: `    r.data.bufferCanvases[i].setAttribute('data-id', 'buffer' + i);`,
  },
  {
    name: 'dynamic canvas presentation size',
    before: `  var canvasContainer = data.canvasContainer;
  canvasContainer.style.width = width + 'px';
  canvasContainer.style.height = height + 'px';
  for (var i = 0; i < r.CANVAS_LAYERS; i++) {
    canvas = data.canvases[i];
    canvas.width = canvasWidth;
    canvas.height = canvasHeight;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
  }
  for (var i = 0; i < r.BUFFER_COUNT; i++) {
    canvas = data.bufferCanvases[i];
    canvas.width = canvasWidth;
    canvas.height = canvasHeight;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
  }`,
    after: `  for (var i = 0; i < r.CANVAS_LAYERS; i++) {
    canvas = data.canvases[i];
    canvas.width = canvasWidth;
    canvas.height = canvasHeight;
  }
  for (var i = 0; i < r.BUFFER_COUNT; i++) {
    canvas = data.bufferCanvases[i];
    canvas.width = canvasWidth;
    canvas.height = canvasHeight;
  }`,
  },
  {
    name: 'export buffer canvas presentation size',
    before: `  buffCanvas.width = width;
  buffCanvas.height = height;
  buffCanvas.style.width = width + 'px';
  buffCanvas.style.height = height + 'px';`,
    after: `  buffCanvas.width = width;
  buffCanvas.height = height;`,
  },
]

const forbiddenDomStyleWrites = [
  /document\.createElement\(['"]style['"]\)/,
  /__________cytoscape_stylesheet/,
  /canvasContainer\.style/,
  /container\.style\[tapHlOffAttr\]/,
  /canvas\.style\[/,
  /canvas\.style\.(?:position|zIndex|visibility|width|height)/,
  /bufferCanvases\[[^\]]+\]\.style/,
  /buffCanvas\.style/,
]

const requiredCssFragments = [
  '.cy-read-graph-canvas-host > .cytoscape-csp-canvas-container',
  '.cytoscape-csp-canvas-container > canvas[data-id^="layer"]',
  'width: 100%',
  'height: 100%',
  'position: absolute',
  'user-select: none',
  '-webkit-tap-highlight-color: transparent',
  'canvas[data-id^="layer0"]',
  'canvas[data-id^="layer1"]',
  'canvas[data-id^="layer2"]',
  'canvas[data-id^="layer3"]',
]

function sha256(value) {
  return createHash('sha256').update(value).digest('hex')
}

function replaceExactlyOnce(source, { name, before, after }) {
  const first = source.indexOf(before)
  const last = source.lastIndexOf(before)
  if (first < 0 || first !== last) {
    throw new Error(`CYTOSCAPE_CSP_SOURCE_MISMATCH:${name}`)
  }
  return source.slice(0, first) + after + source.slice(first + before.length)
}

export function patchCytoscapeSource(source) {
  return replacements.reduce(replaceExactlyOnce, source)
}

export function verifyPatchedSource(source) {
  if (sha256(source) !== PATCHED_SOURCE_SHA256) {
    throw new Error('CYTOSCAPE_CSP_PATCHED_DIGEST_MISMATCH')
  }
  if (!source.includes("r.data.canvasContainer.className = 'cytoscape-csp-canvas-container';")) {
    throw new Error('CYTOSCAPE_CSP_CLASS_MARKER_MISSING')
  }
  for (const pattern of forbiddenDomStyleWrites) {
    if (pattern.test(source)) throw new Error(`CYTOSCAPE_CSP_INLINE_STYLE_WRITE_REMAINS:${pattern.source}`)
  }
}

export function verifyExternalCss(css) {
  for (const fragment of requiredCssFragments) {
    if (!css.includes(fragment)) throw new Error(`CYTOSCAPE_CSP_EXTERNAL_CSS_MISSING:${fragment}`)
  }
}

function parseArgs(argv) {
  const result = { mode: 'patch', packageRoot: undefined, cssPath: undefined }
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === '--verify') result.mode = 'verify'
    else if (arg === '--package-root') result.packageRoot = argv[++index]
    else if (arg === '--css') result.cssPath = argv[++index]
    else throw new Error(`CYTOSCAPE_CSP_UNKNOWN_ARGUMENT:${arg}`)
  }
  return result
}

export async function run({ mode = 'patch', packageRoot, cssPath } = {}) {
  const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
  const frontendRoot = path.resolve(scriptDirectory, '..')
  const resolvedPackageRoot = path.resolve(packageRoot ?? path.join(frontendRoot, 'node_modules/cytoscape'))
  const resolvedCssPath = path.resolve(cssPath ?? path.join(frontendRoot, 'src/components/graph/CytoscapeReadGraph.css'))
  const packageJson = JSON.parse(await readFile(path.join(resolvedPackageRoot, 'package.json'), 'utf8'))
  if (packageJson.name !== 'cytoscape' || packageJson.version !== SUPPORTED_VERSION) {
    throw new Error(`CYTOSCAPE_CSP_UNSUPPORTED_VERSION:${packageJson.name ?? 'unknown'}@${packageJson.version ?? 'unknown'}`)
  }
  if (packageJson.module !== 'dist/cytoscape.esm.mjs' || packageJson.exports?.['.']?.import !== './dist/cytoscape.esm.mjs') {
    throw new Error('CYTOSCAPE_CSP_UNSUPPORTED_BROWSER_ENTRYPOINT')
  }

  const sourcePath = path.join(resolvedPackageRoot, 'dist/cytoscape.esm.mjs')
  const source = await readFile(sourcePath, 'utf8')
  verifyExternalCss(await readFile(resolvedCssPath, 'utf8'))
  const sourceDigest = sha256(source)
  if (sourceDigest === PRISTINE_SOURCE_SHA256) {
    if (mode === 'verify') throw new Error('CYTOSCAPE_CSP_PATCH_NOT_APPLIED')
    const patched = patchCytoscapeSource(source)
    verifyPatchedSource(patched)
    await writeFile(sourcePath, patched, 'utf8')
  } else if (sourceDigest !== PATCHED_SOURCE_SHA256) {
    throw new Error(`CYTOSCAPE_CSP_UNSUPPORTED_SOURCE:${sourceDigest}`)
  }

  verifyPatchedSource(await readFile(sourcePath, 'utf8'))
  return { version: SUPPORTED_VERSION, source: sourcePath, digest: PATCHED_SOURCE_SHA256 }
}

const invokedDirectly = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
if (invokedDirectly) {
  run(parseArgs(process.argv.slice(2)))
    .then(({ version, digest }) => process.stdout.write(`CYTOSCAPE_CSP_PATCH_OK ${version} sha256:${digest}\n`))
    .catch((error) => {
      process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`)
      process.exitCode = 1
    })
}
