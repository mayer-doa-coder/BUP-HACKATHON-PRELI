import { useEffect, useState } from "react";
import { fetchHealth } from "../api/client";

type Status = "checking" | "ok" | "down";

/** Pings /health on mount so the user can see at a glance whether the backend is reachable. */
export function HealthBadge() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then((body) => setStatus(body.status === "ok" ? "ok" : "down"))
      .catch(() => setStatus("down"));
    return () => controller.abort();
  }, []);

  const label = status === "checking" ? "checking…" : status === "ok" ? "backend online" : "backend unreachable";

  return (
    <span className={`health-badge health-badge--${status}`}>
      <span className="health-badge__dot" aria-hidden="true" />
      {label}
    </span>
  );
}
