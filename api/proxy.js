// Vercel proxy for Git deployments built from the repository root.
// Browser -> /api/<path> -> backend EC2. The token stays server-side.

export const config = { runtime: 'edge' }

export default async function handler(req) {
  const url = new URL(req.url)
  const backend = process.env.BACKEND_URL
  const token = process.env.BACKEND_API_TOKEN
  if (!backend) {
    return new Response('BACKEND_URL not configured', { status: 500 })
  }

  let tailPath = url.searchParams.get('p') ?? ''
  if (!tailPath) {
    tailPath = url.pathname.replace(/^\/api\/?/, '').replace(/^proxy\/?/, '')
  }
  const query = new URLSearchParams(url.searchParams)
  query.delete('p')
  const qs = query.toString()
  const target =
    backend.replace(/\/$/, '') +
    '/' +
    tailPath.replace(/^\//, '') +
    (qs ? '?' + qs : '')

  const headers = new Headers(req.headers)
  if (token) headers.set('authorization', `Bearer ${token}`)
  headers.delete('host')
  headers.delete('x-forwarded-host')
  headers.delete('x-forwarded-proto')

  const init = {
    method: req.method,
    headers,
    redirect: 'manual',
  }
  if (!['GET', 'HEAD'].includes(req.method)) {
    init.body = req.body
    init.duplex = 'half'
  }

  try {
    const upstream = await fetch(target, init)
    const respHeaders = new Headers(upstream.headers)
    respHeaders.delete('content-encoding')
    respHeaders.delete('transfer-encoding')
    respHeaders.delete('connection')
    return new Response(upstream.body, {
      status: upstream.status,
      headers: respHeaders,
    })
  } catch (e) {
    return new Response(`proxy error: ${e?.message ?? e}`, { status: 502 })
  }
}
