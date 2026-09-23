import EmptyState from "@/components/EmptyState";

export default function Page() {
  return (
    <div>
      <h1 className="text-xl font-bold text-text-primary mb-4">Dashboard</h1>
      <EmptyState icon="🚧" title="Coming next" message="This page is being built." />
    </div>
  );
}
