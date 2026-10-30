import { GlobalPage } from "./pages/GlobalPage";
import { Navigate, Route, Routes } from "react-router-dom";
import { BrainPage } from "./pages/BrainPage";
import { AppShell } from "./components/AppShell";
import { HomePage } from "./pages/HomePage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { SearchPage } from "./pages/SearchPage";
import { ProjectPage } from "./pages/ProjectPage";
import { HelpArticlePage, HelpPage } from "./pages/HelpPages";
import { ActivityPage } from "./pages/ActivityPage";
import { AllTasksPage } from "./pages/AllTasksPage";
import { SettingsPage } from "./pages/SettingsPage";
import { UsagePage } from "./pages/UsagePage";
import { ReviewInboxPage } from "./pages/ReviewInboxPage";

export function App() {
  return <AppShell>
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/projects" element={<ProjectsPage />} />
      <Route path="/projects/:projectId" element={<ProjectPage />} />
      <Route path="/projects/:projectId/:section" element={<ProjectPage />} />
      <Route path="/brain" element={<BrainPage />} />
      <Route path="/global" element={<GlobalPage />} />
      <Route path="/global/:section" element={<GlobalPage />} />
      <Route path="/search" element={<SearchPage />} />
      <Route path="/tasks" element={<AllTasksPage />} />
      <Route path="/activity" element={<ActivityPage />} />
      <Route path="/review" element={<ReviewInboxPage />} />
      <Route path="/usage" element={<UsagePage />} />
      <Route path="/help" element={<HelpPage />} />
      <Route path="/help/:slug" element={<HelpArticlePage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </AppShell>;
}
