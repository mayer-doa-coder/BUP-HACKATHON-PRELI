import { ApiError, UnexpectedResponseError } from "../api/client";

interface Props {
  error: unknown;
}

const STATUS_LABEL: Record<number, string> = {
  400: "400 — structurally invalid request",
  413: "413 — request too large",
  422: "422 — semantically invalid request",
  500: "500 — internal error",
};

/** Renders the backend's error envelope (app/api/errors.py) in a readable, classified form. */
export function ErrorPanel({ error }: Props) {
  if (error instanceof ApiError) {
    const label = STATUS_LABEL[error.status] ?? `${error.status} — request failed`;
    return (
      <div className="error-panel" role="alert">
        <div className="error-panel__status">{label}</div>
        <p className="error-panel__message">{error.message}</p>
        {error.details.length > 0 && (
          <ul className="error-panel__details">
            {error.details.map((detail, index) => (
              <li key={index}>{detail}</li>
            ))}
          </ul>
        )}
        <p className="error-panel__correlation">
          Correlation ID: <code>{error.correlationId}</code>
        </p>
      </div>
    );
  }

  if (error instanceof UnexpectedResponseError) {
    return (
      <div className="error-panel" role="alert">
        <div className="error-panel__status">{error.status} — unexpected response</div>
        <p className="error-panel__message">{error.message}</p>
      </div>
    );
  }

  const message =
    error instanceof Error
      ? error.message
      : "Could not reach the backend. Is it running, and is the API base URL correct?";

  return (
    <div className="error-panel" role="alert">
      <div className="error-panel__status">Request failed</div>
      <p className="error-panel__message">{message}</p>
    </div>
  );
}
