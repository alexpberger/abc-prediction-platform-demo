import { useState } from "react";

import { AppShell, type Section } from "./layout/AppShell";
import { LoginPage } from "./pages/LoginPage";

type Screen = "login" | Section;

export function App() {
  const [screen, setScreen] = useState<Screen>("login");

  if (screen === "login") {
    return <LoginPage onSignedIn={() => setScreen("home")} />;
  }

  return (
    <AppShell
      section={screen}
      onNavigate={setScreen}
      onSignOut={() => setScreen("login")}
    />
  );
}
