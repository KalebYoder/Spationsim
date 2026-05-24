import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function ProtectedRoute({ children }) {
  const { player } = useAuth()
  if (player === undefined) return <p>Loading…</p>
  if (!player) return <Navigate to="/login" replace />
  return children
}
