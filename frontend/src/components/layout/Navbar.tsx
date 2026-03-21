import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { Button } from '../ui/Button'

const links = [
  { to: '/dashboard', label: 'Open Bets' },
  { to: '/bets/my',   label: 'My Bets' },
  { to: '/wallet',    label: 'Wallet' },
]

export function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <header className="border-b border-gray-800 bg-gray-900">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        {/* Brand */}
        <NavLink to="/dashboard" className="text-lg font-bold text-brand-400 tracking-tight">
          Buddy<span className="text-white">Bet</span>
        </NavLink>

        {/* Nav links */}
        <nav className="flex items-center gap-1">
          {links.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                [
                  'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-gray-800 text-white'
                    : 'text-gray-400 hover:bg-gray-800 hover:text-white',
                ].join(' ')
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Right: place bet + user */}
        <div className="flex items-center gap-3">
          <Button size="sm" onClick={() => navigate('/bets/new')}>
            + Place Bet
          </Button>
          <span className="hidden text-sm text-gray-400 sm:block">
            {user?.display_name}
          </span>
          <Button variant="ghost" size="sm" onClick={handleLogout}>
            Log out
          </Button>
        </div>
      </div>
    </header>
  )
}
