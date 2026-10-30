import { t } from "../lib/i18n";
/** Shared HTTP plumbing for every API module: the desktop token, JSON bodies, and readable errors. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

function detailMessage(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    const messages = value.map((item) => detailMessage(item)).filter(Boolean);
    return messages.length ? messages.join(" ") : null;
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return detailMessage(record.msg) ?? detailMessage(record.message) ?? detailMessage(record.detail);
  }
  return null;
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers: {
        ...(options?.body ? { "Content-Type": "application/json" } : {}),
        ...authHeaders(),
        ...options?.headers,
      },
    });
  } catch (error) {
    if (options?.signal?.aborted) throw error;
    throw new ApiError(t("Project Moah could not reach its local service. Check that the backend is running, then try again."), 0);
  }

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      // Some server and proxy errors have no JSON body.
    }
    const message = detailMessage(detail) ?? t("The request failed ({status}). Please try again.", { status: String(response.status) });
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

/** Request options for a JSON call; the body is omitted when there is none. */
export const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

/** The desktop app's API token, when running inside it. */
export const authHeaders = (): Record<string, string> => {
  const token = window.projectBrainDesktop?.apiToken;
  return token ? { "X-Project-Brain-Token": token } : {};
};
