/**
 * Same-origin BFF: browser -> Next.js -> FastAPI.
 *
 * The access token stays in an HttpOnly cookie. The browser never receives it,
 * and every user_id sent by old UI code is replaced with the authenticated id.
 */
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const SESSION_COOKIE = "sparklearn_session";
const BACKEND =
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "http://localhost:8000";

type RouteContext = { params: Promise<{ path: string[] }> };

function tokenSubject(token: string | undefined): string | null {
  if (!token) return null;
  try {
    const payload = JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString("utf8")) as { sub?: unknown };
    return typeof payload.sub === "string" && payload.sub ? payload.sub : null;
  } catch {
    return null;
  }
}

function jsonError(detail: string, status: number) {
  return NextResponse.json({ detail }, { status });
}

function isLoopbackRequest(req: NextRequest) {
  // Next standalone uses its internal bind address in nextUrl. Nginx preserves
  // the actual loopback Host, including the public local port.
  return /^(localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?$/i.test(req.headers.get("host") || "");
}

function isSecureRequest(req: NextRequest) {
  return req.nextUrl.protocol === "https:" || (
    process.env.TRUST_PROXY_HEADERS === "true" && req.headers.get("x-forwarded-proto") === "https"
  );
}

async function authResponse(req: NextRequest, action: "login" | "register") {
  const upstream = await fetch(`${BACKEND}/api/auth/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: await req.text(),
    cache: "no-store",
  });
  const payload = await upstream.json().catch(() => ({ detail: `HTTP ${upstream.status}` })) as {
    access_token?: string;
    expires_in?: number;
    user?: unknown;
    detail?: string;
  };
  if (!upstream.ok || !payload.access_token) {
    return NextResponse.json(payload, { status: upstream.status });
  }

  const response = NextResponse.json({ user: payload.user }, { status: upstream.status });
  const secure = isSecureRequest(req);
  response.cookies.set(SESSION_COOKIE, payload.access_token, {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: Math.max(60, Number(payload.expires_in) || 60 * 60 * 24 * 7),
  });
  return response;
}

async function proxy(req: NextRequest, { params }: RouteContext) {
  const { path: routePath } = await params;
  const path = [...routePath];
  // Worker token is scoped by the backend to this prefix and one configured owner.
  // Never substitute a website session cookie for this explicit pairing secret.
  if (path[0] === "personal-image-worker") {
    const secure = isSecureRequest(req) || isLoopbackRequest(req);
    if (!secure) return jsonError("图片接入需要 HTTPS", 400);
    const validPath = (path.length === 2 && path[1] === "claim") ||
      (path.length === 3 && /^[a-f0-9]{64}$/.test(path[1]) && ["heartbeat", "submitted", "fail", "complete", "finish"].includes(path[2])) ||
      // Multi-image answers upload each picture by its 1-based position.
      (path.length === 4 && /^[a-f0-9]{64}$/.test(path[1]) && path[2] === "image" && /^[1-9]$/.test(path[3]));
    if (req.method !== "POST" || !validPath) return jsonError("接口不存在", 404);
    const authorization = req.headers.get("authorization");
    if (!authorization) return jsonError("图片接入程序未授权", 401);
    const headers = new Headers({ Authorization: authorization });
    for (const name of ["content-type", "x-image-lease"]) {
      const value = req.headers.get(name);
      if (value) headers.set(name, value);
    }
    const maxBytes = path[2] === "complete" || path[2] === "image" ? 20 * 1024 * 1024 : 2048;
    const reader = req.body?.getReader();
    const parts: Uint8Array[] = [];
    let size = 0;
    if (reader) {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        size += chunk.value.byteLength;
        if (size > maxBytes) { await reader.cancel(); return jsonError("请求过大", 413); }
        parts.push(chunk.value);
      }
    }
    const response = await fetch(`${BACKEND}/api/${path.join("/")}`, {
      method: "POST", headers, body: Buffer.concat(parts), cache: "no-store", redirect: "error",
    });
    return new Response(response.body, { status: response.status,
      headers: { "Content-Type": response.headers.get("content-type") || "application/json", "Cache-Control": "no-store" } });
  }
  if (path[0] === "auth" && path[1] === "logout" && req.method === "POST") {
    const response = NextResponse.json({ ok: true });
    response.cookies.set(SESSION_COOKIE, "", { httpOnly: true, maxAge: 0, path: "/", sameSite: "lax" });
    return response;
  }
  if (path[0] === "auth" && (path[1] === "login" || path[1] === "register") && req.method === "POST") {
    return authResponse(req, path[1]);
  }

  const token = req.cookies.get(SESSION_COOKIE)?.value;
  const subject = tokenSubject(token);
  const isStatic = path[0] === "static";
  const isPublicHealth = req.method === "GET" && path.length === 1 && path[0] === "health";
  // Audio/image/video elements request the BFF URL directly. They still send
  // the HttpOnly session cookie, so require it here and forward the JWT to the
  // backend ownership check instead of treating generated assets as public.
  const isPublicMaterials = req.method === "GET" && path.length === 1 && path[0] === "materials";
  if (!token && !isPublicHealth && !isPublicMaterials) return jsonError("请先登录", 401);

  // Keep legacy frontend calls working while making the server-side identity canonical.
  if (subject && path[0] === "profile" && path.length > 1) path[1] = subject;
  const joinedPath = path.join("/");
  const upstreamPath = isStatic ? `/${joinedPath}` : `/api/${joinedPath}`;
  const target = new URL(`${BACKEND}${upstreamPath}`);
  req.nextUrl.searchParams.forEach((value, key) => target.searchParams.append(key, value));
  if (subject && target.searchParams.has("user_id")) target.searchParams.set("user_id", subject);

  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  const accept = req.headers.get("accept");
  const range = req.headers.get("range");
  if (contentType) headers.set("Content-Type", contentType);
  if (accept) headers.set("Accept", accept);
  if (range) headers.set("Range", range);
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const init: RequestInit = { method: req.method, headers, cache: "no-store" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    if (contentType?.includes("application/json")) {
      const raw = await req.text();
      if (raw) {
        try {
          const body = JSON.parse(raw) as unknown;
          if (joinedPath === "settings/models" && body && typeof body === "object") {
            const keys = (body as { keys?: Record<string, unknown> }).keys;
            const secure = isSecureRequest(req)
              || isLoopbackRequest(req);
            if (!secure && keys && Object.values(keys).some(value => typeof value === "string" && value.length > 0)) {
              return jsonError("请通过 HTTPS 或本机 localhost 填写 API 密钥", 400);
            }
          }
          if (subject && !["pilot", "materials"].includes(path[0]) && body && typeof body === "object" && !Array.isArray(body)) {
            (body as Record<string, unknown>).user_id = subject;
          }
          init.body = JSON.stringify(body);
        } catch {
          return jsonError("请求 JSON 格式无效", 400);
        }
      }
    } else if (contentType?.includes("multipart/form-data")) {
      const form = await req.formData();
      if (subject) form.set("user_id", subject);
      init.body = form;
      headers.delete("Content-Type"); // fetch must create the new multipart boundary.
    } else {
      const body = await req.arrayBuffer();
      if (body.byteLength > 0) init.body = body;
    }
  }

  const upstream = await fetch(target, init);
  const responseHeaders = new Headers();
  // fetch() may transparently decompress the upstream body, so never forward Content-Length.
  for (const name of ["content-type", "content-range", "accept-ranges", "etag", "last-modified", "x-learning-failure", "x-learning-validation"]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  responseHeaders.set("Cache-Control", isStatic ? "private, max-age=3600" : "no-store");
  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
