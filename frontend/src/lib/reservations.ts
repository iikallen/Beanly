export function reservationMinute(value: string, timeZone: string) {
  return new Intl.DateTimeFormat([], {
    timeZone,
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function reservationTime(value: string, timeZone: string) {
  return new Intl.DateTimeFormat([], {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function localReservationDate(value: string, timeZone: string) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}
