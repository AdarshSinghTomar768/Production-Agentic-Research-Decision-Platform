import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import DashboardPage from './pages/DashboardPage'
import EvalsPage from './pages/EvalsPage'
import KnowledgePage from './pages/KnowledgePage'
import MissionDetailPage from './pages/MissionDetailPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="missions/:id" element={<MissionDetailPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="evals" element={<EvalsPage />} />
        <Route path="*" element={<p className="text-sm text-slate-500">Page not found.</p>} />
      </Route>
    </Routes>
  )
}
