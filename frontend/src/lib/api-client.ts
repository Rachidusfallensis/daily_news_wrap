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
}

/**
 * Wrapper for fetch that automatically handles error checking and Zod validation.
 */
export async function apiFetch<T>(
  url: string,
  schema: z.ZodType<T>,
  options?: ApiOptions
): Promise<T> {
  // Ensure credentials are sent by default for session auth
  const fetchOptions: RequestInit = {
    credentials: 'include',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  }

  try {
    const response = await fetch(url, fetchOptions)

    if (!response.ok) {
      throw new ApiError(`HTTP Error: ${response.status} ${response.statusText}`, response.status)
    }

    // Some endpoints might return 204 No Content
    if (response.status === 204) {
      return null as any
    }

    const data = await response.json()

    if (options?.skipValidation) {
      return data as T
    }

    // Pass data through Zod schema
    const parsedData = schema.safeParse(data)
    if (!parsedData.success) {
      console.error(`[Zod Validation Error] on ${url}:`, parsedData.error.format())
      // We throw the error so it can be handled by the caller or an error boundary
      throw new Error(`Data validation failed for ${url}`)
    }

    return parsedData.data
  } catch (error) {
    // Log unexpected errors
    console.error(`[API Fetch Error] ${url}:`, error)
    throw error
  }
}
