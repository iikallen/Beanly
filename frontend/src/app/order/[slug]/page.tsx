import { PublicOrderClient } from "./public-order-client";

export default async function PublicOrderPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <PublicOrderClient slug={slug} />;
}
