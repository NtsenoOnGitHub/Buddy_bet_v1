import { api } from './client'
import type { TokenResponse, UserResponse } from './types'

export interface RegisterPayload {
  email: string
  password: string
  display_name: string
  phone_number?: string
}

export interface LoginPayload {
  email: string
  password: string
}

export interface ForgotPasswordPayload {
  email: string
}

export interface ForgotPasswordResponse {
  message: string
  /** Only present in development mode. */
  reset_token?: string
}

export interface ResetPasswordPayload {
  token: string
  new_password: string
}

export const authApi = {
  register: (payload: RegisterPayload) =>
    api.post<TokenResponse>('/auth/register', payload),

  login: (payload: LoginPayload) =>
    api.post<TokenResponse>('/auth/login', payload),

  me: () => api.get<UserResponse>('/auth/me'),

  forgotPassword: (payload: ForgotPasswordPayload) =>
    api.post<ForgotPasswordResponse>('/auth/forgot-password', payload),

  resetPassword: (payload: ResetPasswordPayload) =>
    api.post<void>('/auth/reset-password', payload),
}
