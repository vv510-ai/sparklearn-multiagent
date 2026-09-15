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
  const secure = req.nextUrl.protocol === "https:" || req.headers.get("x-forwarded-proto") === "https";
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
  if (!token && !isPublicHealth) return jsonError("请先登录", 401);

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
          if (subject && path[0] !== "pilot" && body && typeof body === "object" && !Array.isArray(body)) {
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
  for (const name of ["content-type", "content-range", "accept-ranges", "etag", "last-modified"]) {
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
