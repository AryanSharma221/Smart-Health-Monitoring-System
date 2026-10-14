/**
 * API Transport & Error Types
 */

export interface ApiResponse<T> {
  data: T;
  status: 'success' | 'error';
  message?: string;
}

export interface ApiError {
  statusCode: number;
  message: string;
  detail?: unknown;
}
