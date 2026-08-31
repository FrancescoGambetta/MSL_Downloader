import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '@/lib/AuthContext';
import { AppSettingsProvider } from '@/lib/AppSettingsContext';
import Landing from '@/pages/Landing';
import Home from '@/pages/Home';
import CatalogManager from '@/pages/CatalogManager';
import NotFound from '@/pages/NotFound';

export default function App() {
  return (
    <AuthProvider>
      <AppSettingsProvider>
        <Router>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/download" element={<Home />} />
            <Route path="/catalog-manager" element={<CatalogManager />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Router>
      </AppSettingsProvider>
    </AuthProvider>
  );
}
