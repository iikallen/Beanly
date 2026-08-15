import { PublicReservationClient } from "./public-reservation-client";

export default async function ReservationPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <PublicReservationClient slug={slug} />;
}
