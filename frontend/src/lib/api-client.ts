import { z } from 'zod'

export class ApiError extends Error {
  public status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

interface ApiOptions extends RequestInit {
  // Option to skip validation if needed
  skipValidation?: boolean
  /** Abort the request after this many ms (default 30s). Pass 0 to disable. */
  timeoutMs?: number
}

/** Default request timeout — long enough for slow LLM endpoints, short enough to avoid hangs. */
const DEFAULT_TIMEOUT_MS = 30_000

/** Extract a human-readable message from a FastAPI error body ({detail: ...}). */
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.clone().json()
    if (typeof body?.detail === 'string') return body.detail
    if (Array.isArray(body?.detail) && body.detail[0]?.msg) return body.detail[0].msg
    if (typeof body?.message === 'string') return body.message
  } catch {
    // Body wasn't JSON — fall through to status text
  }
  return `${response.status} ${response.statusText}`
}

/**
 * Wrapper for fetch that automatically handles error checking and Zod validation.
 */
export async function apiFetch<T>(
  url: string,
  schema: z.ZodType<T>,
  options?: ApiOptions
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, skipValidation, ...rest } = options ?? {}

  // Time out the request unless the caller opted out (timeoutMs === 0) or passed
  // their own signal.
  const controller = new AbortController()
  const timer = timeoutMs > 0 && !rest.signal
    ? setTimeout(() => controller.abort(), timeoutMs)
    : null

  // Ensure credentials are sent by default for session auth
  const fetchOptions: RequestInit = {
    credentials: 'include',
    signal: rest.signal ?? controller.signal,
    ...rest,
    headers: {
      'Content-Type': 'application/json',
      ...rest.headers,
    },
  }

  try {
    const response = await fetch(url, fetchOptions)

    if (!response.ok) {
      throw new ApiError(await readErrorMessage(response), response.status)
    }

    // Some endpoints might return 204 No Content
    if (response.status === 204) {
      return null as any
    }

    const data = await response.json()

    if (skipValidation) {
      return data as T
    }

    // Pass data through Zod schema
    const parsedData = schema.safeParse(data)
    if (!parsedData.success) {
      console.error(`[Zod Validation Error] on ${url}:`, parsedData.error.issues)
      // We throw the error so it can be handled by the caller or an error boundary
      throw new Error(`Data validation failed for ${url}`)
    }

    return parsedData.data
  } catch (error) {
    // Turn an abort (timeout) into a clear, typed error
    if (error instanceof DOMException && error.name === 'AbortError') {
      const timeoutError = new ApiError('La requête a expiré (timeout).', 408)
      console.error(`[API Fetch Error] ${url}:`, timeoutError)
      throw timeoutError
    }
    // Log unexpected errors
    console.error(`[API Fetch Error] ${url}:`, error)
    throw error
  } finally {
    if (timer) clearTimeout(timer)
  }
}
