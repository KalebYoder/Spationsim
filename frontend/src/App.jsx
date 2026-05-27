import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import Layout from './components/Layout'
import Login from './pages/Login'
import Register from './pages/Register'
import NationCreate from './pages/NationCreate'
import Home from './pages/Home'
import Economy from './pages/Economy'
import Facilities from './pages/Facilities'
import Military from './pages/Military'
import Probes from './pages/Probes'
import Planets from './pages/Planets'
import MapView from './pages/MapView'
import Diplomacy from './pages/Diplomacy'
import NationProfile from './pages/NationProfile'
import Mail from './pages/Mail'
import EventLog from './pages/EventLog'
import FriendsList from './pages/FriendsList'

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
      <Routes>
        {/* Auth pages — no layout */}
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/create-nation" element={
          <ProtectedRoute><NationCreate /></ProtectedRoute>
        } />

        {/* Game pages — sidebar layout, requires nation */}
        <Route element={<NationGate><Layout /></NationGate>}>
          <Route path="/"           element={<Home />} />
          <Route path="/economy"    element={<Economy />} />
          <Route path="/facilities" element={<Facilities />} />
          <Route path="/military"   element={<Military />} />
          <Route path="/probes"     element={<Probes />} />
          <Route path="/planets"    element={<Planets />} />
          <Route path="/map"        element={<MapView />} />
          <Route path="/diplomacy"      element={<Diplomacy />} />
          <Route path="/friends"        element={<FriendsList />} />
          <Route path="/nations/:id"    element={<NationProfile />} />
          <Route path="/mail"           element={<Mail />} />
          <Route path="/log"        element={<EventLog />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  )
}
