import { Route, Routes } from "react-router";
import { WelcomePage } from "./features/welcome/WelcomePage";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<WelcomePage />} />
    </Routes>
  );
}
