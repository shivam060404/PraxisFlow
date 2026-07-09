import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { ExecutionBoard } from "@/components/dashboard/execution-board";

export default function BoardPage() {
  return (
    <DashboardLayout>
      <ExecutionBoard />
    </DashboardLayout>
  );
}