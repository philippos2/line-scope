export type JsonObject = Record<string, unknown>;
export interface Envelope {
  request_id: string;
  context_id: string | null;
  status: "ok" | "partial" | "error";
  answer: string | null;
  data: JsonObject;
  evidence: JsonObject;
  warnings: unknown[];
  errors: unknown[];
}
export function object(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
export class ApiError extends Error {
  constructor(
    public code: string,
    public requestId?: string,
  ) {
    super(code);
  }
}
export function envelope(value: unknown): Envelope {
  if (
    !object(value) ||
    !["ok", "partial", "error"].includes(String(value.status)) ||
    typeof value.request_id !== "string" ||
    !(value.context_id === null || typeof value.context_id === "string") ||
    !(value.answer === null || typeof value.answer === "string") ||
    !object(value.data) ||
    !object(value.evidence) ||
    !Array.isArray(value.errors) ||
    !Array.isArray(value.warnings)
  )
    throw new ApiError("INVALID_RESPONSE");
  return value as unknown as Envelope;
}
export async function request(
  token: string,
  path:
    | "/health/ready"
    | "/agent"
    | "/decisions/compare"
    | `/maintenance-inputs/${string}`
    | `/safety-inputs/${string}`
    | `/capacity-inputs/${string}`
    | "/economic-inputs/search"
    | "/economic-inputs/prepare"
    | `/economic-inputs/${string}`
    | "/session"
    | "/session/login"
    | "/session/logout"
    | `/update-requests/${string}`
    | `/approvals/${string}/approve`
    | `/approvals/${string}/reject`,
  body?: JsonObject,
  signal?: AbortSignal,
  retryKey?: string,
  method?: "GET" | "POST",
): Promise<Envelope> {
  let authorization: Headers;
  try {
    authorization = new Headers({ Authorization: "Bearer " + token });
  } catch {
    throw new ApiError("INVALID_TOKEN_FORMAT");
  }
  let response: Response;
  try {
    response = await fetch("/api" + path, {
      method: method ?? (body ? "POST" : "GET"),
      headers: {
        ...(token
          ? { Authorization: authorization.get("Authorization")! }
          : {}),
        "X-LineScope-Browser": "1",
        ...(retryKey ? { "Idempotency-Key": retryKey } : {}),
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
      signal,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError("CONNECTION_FAILED");
  }
  let result: Envelope;
  try {
    result = envelope(await response.json());
  } catch {
    throw new ApiError("INVALID_RESPONSE");
  }
  if (!response.ok || result.status === "error") {
    const first = result.errors[0];
    const code =
      object(first) &&
      typeof first.code === "string" &&
      /^[A-Z_]{1,80}$/.test(first.code)
        ? first.code
        : "API_ERROR";
    throw new ApiError(code, result.request_id);
  }
  return result;
}
