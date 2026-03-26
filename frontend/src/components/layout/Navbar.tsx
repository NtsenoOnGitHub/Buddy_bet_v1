import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { Button } from '../ui/Button'

const userLinks = [
  { to: '/matches',   label: 'Matches'   },
  { to: '/dashboard', label: 'Open Bets' },
  { to: '/bets/my',   label: 'My Bets'   },
  { to: '/wallet',    label: 'Wallet'    },
]

const adminLinks = [
  { to: '/admin',                label: 'Pending' },
  { to: '/admin/confirm-result', label: 'Confirm Result' },
]

export function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const isAdmin = user?.role === 'admin'

  function handleLogout() {
    logout()
    navigate('/login')
  }

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    [
      'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
      isActive
        ? 'bg-gray-800 text-white'
        : 'text-gray-400 hover:bg-gray-800 hover:text-white',
    ].join(' ')

  return (
    <header className="border-b border-gray-800 bg-gray-900">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        {/* Brand */}
        <NavLink to="/dashboard" className="tracking-tight text-lg font-bold text-brand-400">
          Buddy<span className="text-white">Bet</span>
        </NavLink>

        {/* Nav links */}
        <nav className="flex items-center gap-1">
          {userLinks.map(({ to, label }) => (
            <NavLink key={to} to={to} className={navLinkClass}>
              {label}
            </NavLink>
          ))}
          {isAdmin && (
            <>
              <span className="mx-1 text-gray-700">|</span>
              {adminLinks.map(({ to, label }) => (
                <NavLink key={to} to={to} end className={navLinkClass}>
                  {label}
                </NavLink>
              ))}
            </>
          )}
        </nav>

        {/* Right: place bet + user */}
        <div className="flex items-center gap-3">
          <Button size="sm" onClick={() => navigate('/bets/new')}>
            + Place Bet
          </Button>
          <span className="hidden text-sm text-gray-400 sm:block">
            {user?.display_name}
            {isAdmin && <span className="ml-1 text-xs text-yellow-500">(admin)</span>}
          </span>
          <Button variant="ghost" size="sm" onClick={handleLogout}>
            Log out
          </Button>
        </div>
      </div>
    </header>
  )
}
