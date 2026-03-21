import { Outlet } from 'react-router-dom'
import { Navbar } from './Navbar'

export default function AppLayout() {
  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="mx-auto max-w-5xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}
