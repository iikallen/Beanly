import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Beanly POS",
    short_name: "Beanly",
    description: "Offline-ready point of sale for Beanly",
    start_url: "/app/pos",
    display: "standalone",
    background_color: "#f7f8f6",
    theme_color: "#255233",
    icons: [
      { src: "/beanly-icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/beanly-icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/beanly-icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/beanly-icon.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
    ],
  };
}
