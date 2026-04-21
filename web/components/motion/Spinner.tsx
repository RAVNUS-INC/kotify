export type SpinnerProps = {
  size?: number;
  color?: string;
  className?: string;
  title?: string;
};

export function Spinner({
  size = 14,
  color = 'currentColor',
  className,
  title,
}: SpinnerProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      className={className}
      style={{ animation: 'k-spin 0.7s linear infinite' }}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={!title}
    >
      <circle
        cx="8"
        cy="8"
        r="6"
        fill="none"
        stroke={color}
        strokeOpacity="0.2"
        strokeWidth="2"
      />
      <path
        d="M14 8a6 6 0 0 0-6-6"
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}
