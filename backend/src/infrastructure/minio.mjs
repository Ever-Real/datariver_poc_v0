/* global Buffer */
// Dependencies are supplied by bootstrap; this module never constructs a shared client.
export function createInfrastructureMinio(deps) {
function sha256(value) {
  return deps.createHash('sha256').update(value).digest('hex')
}

function hmac(key, value) {
  return deps.createHmac('sha256', key).update(value).digest()
}

function awsEncode(value) {
  return encodeURIComponent(value).replace(/[!'()*]/g, (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`)
}

async function minioObject(method, bucket, key, body = Buffer.alloc(0), contentType = 'application/octet-stream') {
  if (!deps.minio) throw Object.assign(new Error('MinIO is not configured.'), { statusCode: 503 })
  if (!Object.values(deps.minio.buckets).includes(bucket)) throw Object.assign(new Error('Bucket is not allowlisted.'), { statusCode: 400 })
  const endpoint = new deps.URL(deps.minio.url)
  const canonicalPath = `${endpoint.pathname.replace(/\/$/, '')}/${awsEncode(bucket)}/${key.split('/').map(awsEncode).join('/')}`
  const payloadHash = sha256(body)
  const now = new Date()
  const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, '')
  const date = amzDate.slice(0, 8)
  const host = endpoint.host
  const signedHeaders = 'host;x-amz-content-sha256;x-amz-date'
  const canonicalHeaders = `host:${host}\nx-amz-content-sha256:${payloadHash}\nx-amz-date:${amzDate}\n`
  const canonicalRequest = `${method}\n${canonicalPath}\n\n${canonicalHeaders}\n${signedHeaders}\n${payloadHash}`
  const scope = `${date}/${deps.minio.region}/s3/aws4_request`
  const stringToSign = `AWS4-HMAC-SHA256\n${amzDate}\n${scope}\n${sha256(canonicalRequest)}`
  const dateKey = hmac(`AWS4${deps.minio.secretKey}`, date)
  const regionKey = hmac(dateKey, deps.minio.region)
  const serviceKey = hmac(regionKey, 's3')
  const signingKey = hmac(serviceKey, 'aws4_request')
  const signature = deps.createHmac('sha256', signingKey).update(stringToSign).digest('hex')
  const url = new deps.URL(endpoint)
  url.pathname = canonicalPath
  const response = await deps.providerFetch(url, {
    method,
    headers: {
      Authorization: `AWS4-HMAC-SHA256 Credential=${deps.minio.accessKey}/${scope}, SignedHeaders=${signedHeaders}, Signature=${signature}`,
      'Content-Type': contentType,
      'x-amz-content-sha256': payloadHash,
      'x-amz-date': amzDate,
    },
    body: ['GET', 'HEAD'].includes(method) ? undefined : body,
  })
  await deps.requireOk(response, 'MinIO')
  return response
}

return { sha256, hmac, awsEncode, minioObject }
}
