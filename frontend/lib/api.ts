import type { SparkEvent } from "./types";

/** 所有请求经 Next BFF(app/api/[...path]/route.ts)转发到后端,规避浏览器 CORS。 */
const BASE = "/api";

/** 后端生成的 /static/* 资源继续经同一 BFF 获取，避免浏览器误请求 Next 端口。 */
export function apiAssetUrl(url?: string): string | undefined {
  if (!url) return undefined;
  return url.startsWith("/static/") ? `${BASE}${url}` : url;
}

/** POST + SSE:逐事件回调;返回 abort 函数。 */
export function postSSE(
  path: string,
  body: unknown,
  onEvent: (ev: SparkEvent) => void,
  onClose?: () => void,
): () => void {
  const ctrl = new AbortController();
  (async () => {
    try {
      const res = await fetch(`${BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) {
        let detail = `HTTP ${res.status}`;
        try {
          const data = await res.json() as { detail?: string };
          detail = data.detail || detail;
        } catch {
          try {
            const text = await res.text();
            if (text) detail = `${detail}: ${text.slice(0, 180)}`;
          } catch {
            /* keep status only */
          }
        }
        onEvent({ type: "error", detail });
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const line = frame.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          try {
            onEvent(JSON.parse(line.slice(6)) as SparkEvent);
          } catch {
            /* 跳过坏帧 */
          }
        }
      }
    } catch (e: unknown) {
      if ((e as Error)?.name !== "AbortError")
        onEvent({ type: "error", detail: String(e) });
    } finally {
      onClose?.();
    }
  })();
  return () => ctrl.abort();
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) {
    let detail = text || `HTTP ${res.status}`;
    try {
      const data = JSON.parse(text) as { detail?: string };
      detail = data.detail || detail;
    } catch {
      /* keep raw response text */
    }
    throw new Error(`POST ${path} → ${res.status}: ${detail.slice(0, 180)}`);
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`POST ${path} 返回了不完整的数据，请重试`);
  }
}

export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "POST", body: form });
  if (!res.ok) {
    const text = await res.text();
    let message = text || `上传失败: HTTP ${res.status}`;
    try {
      const data = JSON.parse(text) as { detail?: string };
      message = data.detail || message;
    } catch {
      /* keep raw response text */
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export const USER_ID = "demo_user";
