import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react'
import { tokenStore } from '../api/client'
import { authApi } from '../api/auth'
import type { UserResponse } from '../api/types'

interface AuthState {
  token: string | null
  user: UserResponse | null
  login: (token: string, user: UserResponse) => void
  logout: () => void
  isLoading: boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(tokenStore.get)
  const [user, setUser] = useState<UserResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // On mount: if a token exists in storage, fetch the current user to
  // re-hydrate the session (handles page refresh).
  useEffect(() => {
    if (!token) {
      setIsLoading(false)
      return
    }
    authApi
      .me()
      .then((u) => setUser(u))
      .catch(() => {
        // Token expired or invalid — clear it.
        tokenStore.clear()
        setToken(null)
      })
      .finally(() => setIsLoading(false))
  }, []) // run once on mount

  const login = useCallback((newToken: string, newUser: UserResponse) => {
    tokenStore.set(newToken)
    setToken(newToken)
    setUser(newUser)
  }, [])

  const logout = useCallback(() => {
    tokenStore.clear()
    setToken(null)
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ token, user, login, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
