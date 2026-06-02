import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import { NationProvider } from './context/NationContext'
import ProtectedRoute from './components/ProtectedRoute'
import Layout from './components/Layout'
import Login from './pages/Login'
import Register from './pages/Register'
import NationCreate from './pages/NationCreate'
import Home from './pages/Home'

const Economy     = lazy(() => import('./pages/Economy'))
const Facilities  = lazy(() => import('./pages/Facilities'))
const Military    = lazy(() => import('./pages/Military'))
const Probes      = lazy(() => import('./pages/Probes'))
const Planets     = lazy(() => import('./pages/Planets'))
const MapView     = lazy(() => import('./pages/MapView'))
const Diplomacy   = lazy(() => import('./pages/Diplomacy'))
const NationProfile = lazy(() => import('./pages/NationProfile'))
const CombatLog   = lazy(() => import('./pages/CombatLog'))
const Mail        = lazy(() => import('./pages/Mail'))
const EventLog    = lazy(() => import('./pages/EventLog'))
const FriendsList = lazy(() => import('./pages/FriendsList'))
const Trade       = lazy(() => import('./pages/Trade'))
const ProbeMarket = lazy(() => import('./pages/ProbeMarket'))

function NationGate({ children }) {
  const { player } = useAuth()
  if (player === undefined) return <p style={{ color: 'var(--text-muted)', padding: 32 }}>Loading&hellip;</p>
  if (!player) return <Navigate to="/login" replace />
  if (!player.has_nation) return <Navigate to="/create-nation" replace />
  return children
}

export default function App() {
  return (
    <AuthProvider>
      <Suspense fallback={<p style={{ color: 'var(--text-muted)', padding: 32 }}>Loading&hellip;</p>}>
        <Routes>
          {/* Auth pages — no layout */}
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/create-nation" element={
            <ProtectedRoute><NationCreate /></ProtectedRoute>
          } />

          {/* Game pages — sidebar layout, requires nation */}
          <Route element={<NationGate><NationProvider><Layout /></NationProvider></NationGate>}>
            <Route path="/"           element={<Home />} />
            <Route path="/economy"    element={<Economy />} />
            <Route path="/facilities" element={<Facilities />} />
            <Route path="/military"   element={<Military />} />
            <Route path="/probes"     element={<Probes />} />
            <Route path="/planets"    element={<Planets />} />
            <Route path="/map"        element={<MapView />} />
            <Route path="/diplomacy"      element={<Diplomacy />} />
            <Route path="/friends"        element={<FriendsList />} />
            <Route path="/trade"          element={<Trade />} />
            <Route path="/market"         element={<ProbeMarket />} />
            <Route path="/nations/:id"    element={<NationProfile />} />
            <Route path="/nations/:id/wars/:opponentId" element={<CombatLog />} />
            <Route path="/mail"           element={<Mail />} />
            <Route path="/log"        element={<EventLog />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AuthProvider>
  )
}
