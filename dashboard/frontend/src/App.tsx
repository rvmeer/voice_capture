import { BrowserRouter, Routes, Route } from 'react-router-dom';
import HomePage from './pages/HomePage';
import LivePage from './pages/LivePage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/live/:recordingId" element={<LivePage />} />
      </Routes>
    </BrowserRouter>
  );
}
