import { PublicReservationStatus } from "./public-reservation-status";

export default async function ReservationStatusPage({ params }: { params: Promise<{ guestAccessToken: string }> }) {
  const { guestAccessToken } = await params;
  return <PublicReservationStatus guestAccessToken={guestAccessToken} />;
}
