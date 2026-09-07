/* global Buffer */
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createInterfacesHttpStatic(deps) {
function staticFile(requestPath) {
  const decoded = decodeURIComponent(requestPath)
  const normalizedPath = deps.normalize(decoded).replace(/^[/\\]+/, '')
  const candidate = deps.resolve(deps.staticDirectory, normalizedPath || 'index.html')
  if (!candidate.startsWith(`${deps.staticDirectory}${deps.sep}`)) return undefined
  if (deps.existsSync(candidate) && deps.statSync(candidate).isFile()) return candidate
  return deps.join(deps.staticDirectory, 'index.html')
}

function serveStatic(request, response, url) {
  const file = staticFile(url.pathname)
  if (!file || !deps.existsSync(file)) return deps.problem(response, 404, 'STATIC_NOT_FOUND', 'POC static build is missing.')
  const extension = deps.extname(file)
  const headers = {
    'Cache-Control': extension === '.html' ? 'no-store' : 'public, max-age=31536000, immutable',
    'Content-Type': deps.mimeTypes[extension] || 'application/octet-stream',
    ...deps.securityHeaders(),
  }
  if (extension === '.html') {
    const body = deps.readFileSync(file, 'utf8')
      .replace('<head>', '<head>\n    <base href="/">')
      .replace('</head>', '  <script src="/poc-runtime-config.js"></script>\n  </head>')
    response.writeHead(200, { ...headers, 'Content-Length': Buffer.byteLength(body) })
    return response.end(request.method === 'HEAD' ? undefined : body)
  }
  const size = deps.statSync(file).size
  response.writeHead(200, { ...headers, 'Content-Length': size })
  if (request.method === 'HEAD') return response.end()
  return deps.createReadStream(file).pipe(response)
}

return { staticFile, serveStatic }
}
