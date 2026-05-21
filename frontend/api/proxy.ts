// Vercel Edge proxy. Browser → /api/<path> → this function → backend EC2.
// Adds the shared bearer token server-side so it never reaches the browser.

export const config = { runtime: 'edge' }

export default async function handler(req: Request): Promise<Response> {
  const url = new URL(req.url)
  const backend = process.env.BACKEND_URL
  const token = process.env.BACKEND_API_TOKEN
  if (!backend) {
    return new Response(
      'BACKEND_URL is not configured on Vercel. Set it to the deployed FastAPI backend base URL.',
      { status: 500 },
    )
  }
  // Vercel rewrite sends "/api/<anything>" here with the original path tail
  // in ?p=<path>. Fall back to stripping /api from pathname for direct calls.
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

  const init: RequestInit = {
    method: req.method,
    headers,
    redirect: 'manual',
  }
  if (!['GET', 'HEAD'].includes(req.method)) {
    init.body = req.body
    // @ts-expect-error — required for streaming bodies in undici/edge
    init.duplex = 'half'
  }
  try {
    const upstream = await fetch(target, init)
    // Strip hop-by-hop headers that confuse Vercel's edge response.
    const respHeaders = new Headers(upstream.headers)
    respHeaders.delete('content-encoding')
    respHeaders.delete('transfer-encoding')
    respHeaders.delete('connection')
    return new Response(upstream.body, {
      status: upstream.status,
      headers: respHeaders,
    })
  } catch (e: any) {
    return new Response(`proxy error: ${e?.message ?? e}`, { status: 502 })
  }
}
