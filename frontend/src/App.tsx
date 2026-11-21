import { Navigate, Route, Routes } from "react-router";
import { AuthPage } from "./features/auth/AuthPage";
import { ProtectedApp } from "./features/auth/ProtectedApp";
import { DashboardPage } from "./features/dashboard/DashboardPage";
import { ProductsPage } from "./features/catalog/ProductsPage";
import { SuppliersPage } from "./features/suppliers/SuppliersPage";
import { ImportPage } from "./features/imports/ImportPage";
import { ComparisonListPage } from "./features/comparison/ComparisonListPage";
import { ComparisonDetailPage } from "./features/comparison/ComparisonDetailPage";
import { SalesOrdersPage } from "./features/sales/SalesOrdersPage";
import { SalesOrderDetailPage } from "./features/sales/SalesOrderDetailPage";
import { ExpensesPage } from "./features/expenses/ExpensesPage";

export function App() {
  return <Routes>
    <Route path="/login" element={<AuthPage mode="login" />} />
    <Route path="/register" element={<AuthPage mode="register" />} />
    <Route element={<ProtectedApp />}>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/products" element={<ProductsPage />} />
      <Route path="/suppliers" element={<SuppliersPage />} />
      <Route path="/imports" element={<ImportPage />} />
      <Route path="/comparison" element={<ComparisonListPage />} />
      <Route path="/comparison/:runId" element={<ComparisonDetailPage />} />
      <Route path="/sales" element={<SalesOrdersPage />} />
      <Route path="/sales/:orderId" element={<SalesOrderDetailPage />} />
      <Route path="/expenses" element={<ExpensesPage />} />
    </Route>
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>;
}
