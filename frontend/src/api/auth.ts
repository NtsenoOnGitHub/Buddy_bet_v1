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

export const authApi = {
  register: (payload: RegisterPayload) =>
    api.post<TokenResponse>('/auth/register', payload),

  login: (payload: LoginPayload) =>
    api.post<TokenResponse>('/auth/login', payload),

  me: () => api.get<UserResponse>('/auth/me'),
}
