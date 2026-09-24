import type { SparkEvent } from "./types";

/** 所有请求经 Next BFF(app/api/[...path]/route.ts)转发到后端,规避浏览器 CORS。 */
const BASE = "/api";

export const UNAUTHORIZED_EVENT = "sparklearn:unauthorized";

function notifyUnauthorized(status: number) {
  if (status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
}

/** 后端生成的 /static/* 资源继续经同一 BFF 获取，避免浏览器误请求 Next 端口。 */
export function apiAssetUrl(url?: string): string | undefined {
  if (!url) return undefined;
  return url.startsWith("/static/") ? `${BASE}${url}` : url;
}

function connectionMessage(error: unknown): string {
  if ((error as Error)?.name === "AbortError") return "连接等待超时，请重试；已保存的学习记录仍然保留。";
  if (error instanceof TypeError && /fetch|network|load/i.test(error.message)) return "暂时无法连接服务，请检查网络后重试；已保存的学习记录仍然保留。";
  return error instanceof Error ? error.message : String(error);
}

async function withRequestTimeout<T>(run: (signal: AbortSignal) => Promise<T>, timeout: number): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try { return await run(controller.signal); }
  catch (error) { throw new Error(connectionMessage(error)); }
  finally { clearTimeout(timer); }
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
      notifyUnauthorized(res.status);
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
        onEvent({ type: "error", detail: connectionMessage(e) });
    } finally {
      onClose?.();
    }
  })();
  return () => ctrl.abort();
}

export async function apiGet<T>(path: string): Promise<T> {
  return withRequestTimeout(async signal => {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store", signal });
  notifyUnauthorized(res.status);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json() as Promise<T>;
  }, 20_000);
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return withRequestTimeout(async signal => {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const text = await res.text();
  notifyUnauthorized(res.status);
  if (!res.ok) {
    let detail = text || `HTTP ${res.status}`;
    try {
      const data = JSON.parse(text) as { detail?: unknown };
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((item: { loc?: unknown[]; msg?: string }) =>
        `${item.loc?.join(".") || "记录"}: ${item.msg || "格式不正确"}`).join("；");
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
  }, 180_000);
}

export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  return withRequestTimeout(async signal => {
  const res = await fetch(`${BASE}${path}`, { method: "POST", body: form, signal });
  notifyUnauthorized(res.status);
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
  }, 180_000);
}

// This sentinel is overwritten by the BFF with the authenticated JWT subject.
export const USER_ID = "session_user";
