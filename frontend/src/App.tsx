import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import AppLayout from './components/layout/AppLayout'
import { PageSpinner } from './components/ui/Spinner'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import ResetPasswordPage from './pages/ResetPasswordPage'
import DashboardPage from './pages/DashboardPage'
import CreateBetPage from './pages/CreateBetPage'
import MyBetsPage from './pages/MyBetsPage'
import BetDetailPage from './pages/BetDetailPage'
import WalletPage from './pages/WalletPage'
import DepositPage from './pages/DepositPage'
import DepositReturnPage from './pages/DepositReturnPage'
import MatchesPage from './pages/MatchesPage'
import AdminPendingPage from './pages/admin/AdminPendingPage'
import AdminConfirmResultPage from './pages/admin/AdminConfirmResultPage'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { token, isLoading } = useAuth()
  if (isLoading) return <PageSpinner />
  return token ? <>{children}</> : <Navigate to="/login" replace />
}

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { token, user, isLoading } = useAuth()
  if (isLoading) return <PageSpinner />
  if (!token) return <Navigate to="/login" replace />
  if (user?.role !== 'admin') return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />

      {/* Protected */}
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/matches" element={<MatchesPage />} />
        <Route path="/bets/new" element={<CreateBetPage />} />
        <Route path="/bets/my" element={<MyBetsPage />} />
        <Route path="/bets/:betId" element={<BetDetailPage />} />
        <Route path="/wallet" element={<WalletPage />} />
        <Route path="/wallet/deposit" element={<DepositPage />} />
        {/* Both return and cancel URLs point to the same status page */}
        <Route path="/wallet/deposit/return" element={<DepositReturnPage />} />
        <Route path="/wallet/deposit/cancel" element={<DepositReturnPage />} />

        {/* Admin */}
        <Route
          path="/admin"
          element={
            <RequireAdmin>
              <AdminPendingPage />
            </RequireAdmin>
          }
        />
        <Route
          path="/admin/confirm-result"
          element={
            <RequireAdmin>
              <AdminConfirmResultPage />
            </RequireAdmin>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
