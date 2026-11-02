import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import "leaflet/dist/leaflet.css";
import Layout from "@/components/Layout";
import { getToken } from "@/lib/api";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import NewSearch from "@/pages/NewSearch";
import LiveAgent from "@/pages/LiveAgent";
import Coverage from "@/pages/Coverage";
import Prospects from "@/pages/Prospects";
import ProspectDetail from "@/pages/ProspectDetail";
import Assessments from "@/pages/Assessments";
import Campaigns from "@/pages/Campaigns";
import Replies from "@/pages/Replies";
import Notifications from "@/pages/Notifications";
import Services from "@/pages/Services";
import Integrations from "@/pages/Integrations";
import SettingsPage from "@/pages/Settings";

const Protected = ({ children }) => (getToken() ? children : <Navigate to="/login" replace />);

export default function App() {
  return (
    <BrowserRouter>
      <Toaster richColors position="top-right" />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<Protected><Layout /></Protected>}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/search" element={<NewSearch />} />
          <Route path="/live" element={<LiveAgent />} />
          <Route path="/coverage" element={<Coverage />} />
          <Route path="/prospects" element={<Prospects />} />
          <Route path="/prospects/:id" element={<ProspectDetail />} />
          <Route path="/assessments" element={<Assessments />} />
          <Route path="/campaigns" element={<Campaigns />} />
          <Route path="/replies" element={<Replies />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/services" element={<Services />} />
          <Route path="/integrations" element={<Integrations />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
