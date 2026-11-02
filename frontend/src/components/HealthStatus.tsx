interface HealthStatusProps {
  online: boolean | null;
}

export function HealthStatus({ online }: HealthStatusProps) {
  const label = online === null ? 'Seeking the backend' : online ? 'Local backend connected' : 'Backend unavailable';
  const tone = online === null ? 'checking' : online ? 'online' : 'offline';

  return (
    <div className={`health-status health-status--${tone}`} role="status" aria-live="polite">
      <span className="health-status__lamp" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
