import { useState } from 'react'
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
  { to: '/admin',                label: 'Pending'        },
  { to: '/admin/confirm-result', label: 'Confirm Result' },
]

export function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const isAdmin = user?.role === 'admin'
  const [menuOpen, setMenuOpen] = useState(false)

  function handleLogout() {
    logout()
    navigate('/login')
    setMenuOpen(false)
  }

  const desktopLinkClass = ({ isActive }: { isActive: boolean }) =>
    [
      'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
      isActive
        ? 'bg-gray-800 text-white'
        : 'text-gray-400 hover:bg-gray-800 hover:text-white',
    ].join(' ')

  const mobileLinkClass = ({ isActive }: { isActive: boolean }) =>
    [
      'block rounded-lg px-4 py-3 text-base font-medium transition-colors',
      isActive ? 'bg-gray-800 text-white' : 'text-gray-300 hover:bg-gray-800 hover:text-white',
    ].join(' ')

  return (
    <header className="border-b border-gray-800 bg-gray-900">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        {/* Brand */}
        <NavLink to="/dashboard" className="text-lg font-bold tracking-tight text-brand-400">
          Buddy<span className="text-white">Bet</span>
        </NavLink>

        {/* Desktop nav */}
        <nav className="hidden items-center gap-1 md:flex">
          {userLinks.map(({ to, label }) => (
            <NavLink key={to} to={to} className={desktopLinkClass}>
              {label}
            </NavLink>
          ))}
          {isAdmin && (
            <>
              <span className="mx-1 text-gray-700">|</span>
              {adminLinks.map(({ to, label }) => (
                <NavLink key={to} to={to} end className={desktopLinkClass}>
                  {label}
                </NavLink>
              ))}
            </>
          )}
        </nav>

        {/* Desktop right */}
        <div className="hidden items-center gap-3 md:flex">
          <Button size="sm" onClick={() => navigate('/bets/new')}>
            + Place Bet
          </Button>
          <span className="text-sm text-gray-400">
            {user?.display_name}
            {isAdmin && <span className="ml-1 text-xs text-yellow-500">(admin)</span>}
          </span>
          <Button variant="ghost" size="sm" onClick={handleLogout}>
            Log out
          </Button>
        </div>

        {/* Mobile right: quick bet + hamburger */}
        <div className="flex items-center gap-2 md:hidden">
          <Button size="sm" onClick={() => { navigate('/bets/new'); setMenuOpen(false) }}>
            + Bet
          </Button>
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-800 hover:text-white"
            aria-label="Toggle menu"
          >
            {menuOpen ? (
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      {menuOpen && (
        <div className="border-t border-gray-800 bg-gray-900 md:hidden">
          <div className="mx-auto max-w-5xl space-y-1 px-4 py-3">
            {/* User info */}
            <div className="mb-2 border-b border-gray-800 px-4 pb-3 text-sm text-gray-400">
              {user?.display_name}
              {isAdmin && <span className="ml-1 text-xs text-yellow-500">(admin)</span>}
            </div>

            {userLinks.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                className={mobileLinkClass}
                onClick={() => setMenuOpen(false)}
              >
                {label}
              </NavLink>
            ))}

            {isAdmin && (
              <>
                <div className="my-2 border-t border-gray-800" />
                {adminLinks.map(({ to, label }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end
                    className={mobileLinkClass}
                    onClick={() => setMenuOpen(false)}
                  >
                    {label}
                  </NavLink>
                ))}
              </>
            )}

            <div className="border-t border-gray-800 pt-2">
              <button
                onClick={handleLogout}
                className="block w-full rounded-lg px-4 py-3 text-left text-base font-medium text-red-400 transition-colors hover:bg-gray-800"
              >
                Log out
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  )
}
