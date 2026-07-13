/** BFF 代理:浏览器 → /api/* → FastAPI 后端,流式 body 原样透传(SSE 友好)。 */
import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const BACKEND =
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "http://localhost:8000";

async function proxy(req: NextRequest, { params }: { params: { path: string[] } }) {
  const joinedPath = params.path.join("/");
  const upstreamPath = params.path[0] === "static" ? `/${joinedPath}` : `/api/${joinedPath}`;
  const target = `${BACKEND}${upstreamPath}${req.nextUrl.search}`;
  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  const accept = req.headers.get("accept");
  const range = req.headers.get("range");
  if (contentType) headers.set("Content-Type", contentType);
  if (accept) headers.set("Accept", accept);
  if (range) headers.set("Range", range);

  const init: RequestInit = {
    method: req.method,
    headers,
    cache: "no-store",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    const body = await req.arrayBuffer();
    if (body.byteLength > 0) init.body = body;
  }
  const res = await fetch(target, init);
  const responseHeaders = new Headers();
  // fetch() may transparently decompress the upstream body. Forwarding the
  // original compressed Content-Length would truncate larger JSON responses.
  for (const name of ["content-type", "content-range", "accept-ranges", "etag", "last-modified"]) {
    const value = res.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  responseHeaders.set("Cache-Control", params.path[0] === "static" ? "public, max-age=3600" : "no-cache");
  return new Response(res.body, {
    status: res.status,
    headers: responseHeaders,
  });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE };
