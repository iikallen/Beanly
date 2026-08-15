import { PublicOrderStatus } from "./public-order-status";

export default async function StatusPage({ params }: { params: Promise<{ statusToken: string }> }) {
  const { statusToken } = await params;
  return <PublicOrderStatus statusToken={statusToken} />;
}
