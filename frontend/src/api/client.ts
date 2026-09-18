import type { ApiErrorBody, OptimizeRequest, OptimizeResponse } from "./types";

/**
 * In dev, relative `/api` calls are proxied to the real backend by Vite
 * (see vite.config.ts) so the browser never has to deal with CORS. In a
 * production build there is no such proxy, so VITE_API_BASE_URL (if set)
 * is used as an absolute base instead.
 */
const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") || "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly correlationId: string;
  readonly details: string[];

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.error.code;
    this.correlationId = body.error.correlation_id;
    this.details = body.error.details ?? [];
  }
}

/** Raised when the response is not the JSON error envelope the backend defines. */
export class UnexpectedResponseError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "UnexpectedResponseError";
    this.status = status;
  }
}

async function parseErrorBody(response: Response): Promise<ApiErrorBody | null> {
  try {
    const body = (await response.json()) as unknown;
    if (
      body &&
      typeof body === "object" &&
      "error" in body &&
      body.error &&
      typeof (body as ApiErrorBody).error.code === "string"
    ) {
      return body as ApiErrorBody;
    }
    return null;
  } catch {
    return null;
  }
}

export async function fetchHealth(signal?: AbortSignal): Promise<{ status: string }> {
  const response = await fetch(`${BASE_URL}/health`, { signal });
  if (!response.ok) {
    throw new UnexpectedResponseError(response.status, `/health returned ${response.status}`);
  }
  return (await response.json()) as { status: string };
}

export async function optimizeEnergy(
  request: OptimizeRequest,
  signal?: AbortSignal,
): Promise<OptimizeResponse> {
  const response = await fetch(`${BASE_URL}/optimize-energy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    const errorBody = await parseErrorBody(response);
    if (errorBody) {
      throw new ApiError(response.status, errorBody);
    }
    throw new UnexpectedResponseError(
      response.status,
      `/optimize-energy returned ${response.status} with an unrecognized body`,
    );
  }

  return (await response.json()) as OptimizeResponse;
}
