import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './pages/Login'
import Register from './pages/Register'
import NationCreate from './pages/NationCreate'

function Dashboard() {
  const { player, logout } = useAuth()
  return (
    <div>
      <h1>Spationsim</h1>
      <p>Welcome, {player.username}</p>
      <button onClick={logout}>Log out</button>
    </div>
  )
}

function NationGate({ children }) {
  const { player } = useAuth()
  if (player === undefined) return <p>Loading…</p>
  if (!player) return <Navigate to="/login" replace />
  if (!player.has_nation) return <Navigate to="/create-nation" replace />
  return children
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/create-nation" element={
          <ProtectedRoute><NationCreate /></ProtectedRoute>
        } />
        <Route path="/" element={
          <NationGate><Dashboard /></NationGate>
        } />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  )
}
